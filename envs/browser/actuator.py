"""Browser actuator.

Chromium runs headful inside the container (visible over noVNC); Playwright
attaches over CDP. Two observation modes are supported:

* pixel -> page screenshot only
* dom   -> screenshot plus a numbered list of interactive elements

Playwright's async API is used because FastAPI endpoints are async; the sync
API is not safe across the threadpool.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from PIL import Image, ImageChops, ImageStat
from playwright.async_api import async_playwright
from pydantic import BaseModel

STATE: dict = {}
LOCK: asyncio.Lock | None = None


DOM_JS = r"""
() => {
  const SEL = 'a,button,input,select,textarea,summary,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="tab"],[role="menuitem"],[role="option"],[contenteditable="true"],[onclick]';
  document.querySelectorAll('[data-cua-id]').forEach(el => el.removeAttribute('data-cua-id'));
  const out = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  let id = 0;
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
    if (el.disabled) continue;
    id += 1;
    el.setAttribute('data-cua-id', String(id));
    const raw = el.innerText || el.value || el.getAttribute('aria-label') ||
                el.getAttribute('placeholder') || el.getAttribute('alt') ||
                el.getAttribute('title') || '';
    out.push({
      id,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || null,
      label: String(raw).trim().replace(/\s+/g, ' ').slice(0, 80),
      x: Math.round(r.left), y: Math.round(r.top),
      w: Math.round(r.width), h: Math.round(r.height),
      href: el.href || null
    });
    if (out.length >= 200) break;
  }
  return {url: location.href, title: document.title, elements: out};
}
"""

KEYMAP = {
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "meta": "Meta",
    "cmd": "Meta",
    "super": "Meta",
    "return": "Enter",
    "enter": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "space": "Space",
    "backspace": "Backspace",
    "delete": "Delete",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
    "tab": "Tab",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global LOCK
    LOCK = asyncio.Lock()
    pw = await async_playwright().start()
    browser = None
    last: Exception | None = None
    for _ in range(40):
        try:
            browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            break
        except Exception as exc:  # chromium may still be booting
            last = exc
            await asyncio.sleep(0.5)
    if browser is None:
        raise RuntimeError(f"cannot attach to chromium over CDP: {last}")
    STATE["pw"] = pw
    STATE["browser"] = browser
    STATE["png"] = None
    yield
    await pw.stop()


app = FastAPI(title="cua-lab browser actuator", lifespan=lifespan)


def page():
    ctx = STATE["browser"].contexts[0]
    pages = [p for p in ctx.pages if not p.is_closed()]
    if not pages:
        raise RuntimeError("no open page in the browser")
    return pages[-1]


async def shot(p) -> bytes:
    last: Exception | None = None
    for _ in range(5):
        try:
            return await p.screenshot(type="png", timeout=15000)
        except Exception as exc:
            last = exc
            await asyncio.sleep(0.2)
    raise RuntimeError(f"screenshot failed: {last}")


def _diff(a: bytes, b: bytes) -> float:
    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return 255.0
    stat = ImageStat.Stat(ImageChops.difference(ia, ib))
    return sum(stat.mean) / 3.0


async def settle(p, prev: bytes | None, timeout: float = 4.0, interval: float = 0.15, quiet: int = 2, eps: float = 0.4):
    cur = prev if prev is not None else await shot(p)
    stable = 0
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    while loop.time() - t0 < timeout:
        await asyncio.sleep(interval)
        try:
            nxt = await shot(p)
        except Exception:
            continue
        delta = _diff(cur, nxt)
        cur = nxt
        stable = stable + 1 if delta < eps else 0
        if stable >= quiet:
            break
    changed = prev is not None and _diff(prev, cur) > 0.3
    return cur, changed


def _keysym(combo: str | None) -> str:
    parts = [p for p in (combo or "").replace("+", " ").split() if p]
    return "+".join(KEYMAP.get(p.lower(), p) for p in parts)


def _mods(keys: str | None) -> list[str]:
    return [KEYMAP.get(m.lower(), m) for m in (keys or "").replace(" ", "+").split("+") if m]


async def extract(p) -> dict:
    """AX-ish extraction with retries: navigation destroys the execution context."""
    last: Exception | None = None
    for _ in range(5):
        try:
            return await p.evaluate(DOM_JS)
        except Exception as exc:
            last = exc
            await asyncio.sleep(0.2)
    return {"url": p.url, "title": "", "elements": [], "error": str(last)[:200]}


async def dispatch(p, a: dict) -> None:
    t = a.get("type")
    x, y = a.get("x"), a.get("y")

    if t in ("click", "double_click", "triple_click", "right_click", "middle_click"):
        if x is None or y is None:
            raise ValueError("click needs x and y")
        button = {"right_click": "right", "middle_click": "middle"}.get(t, "left")
        clicks = {"double_click": 2, "triple_click": 3}.get(t, 1)
        held = _mods(a.get("keys"))
        for m in held:
            await p.keyboard.down(m)
        try:
            await p.mouse.click(x, y, button=button, click_count=clicks)
        finally:
            for m in reversed(held):
                await p.keyboard.up(m)

    elif t == "move":
        if x is None or y is None:
            raise ValueError("move needs x and y")
        await p.mouse.move(x, y)

    elif t == "drag":
        if None in (x, y, a.get("to_x"), a.get("to_y")):
            raise ValueError("drag needs x, y, to_x, to_y")
        await p.mouse.move(x, y)
        await p.mouse.down()
        await p.mouse.move(a["to_x"], a["to_y"], steps=12)
        await p.mouse.up()

    elif t == "type":
        text = a.get("text") or ""
        if text:
            await p.keyboard.type(text, delay=15)

    elif t == "key":
        combo = _keysym(a.get("keys"))
        if not combo:
            raise ValueError("key needs a combo")
        for _ in range(max(1, int(a.get("amount") or 1))):
            await p.keyboard.press(combo)

    elif t == "hold_key":
        combo = _keysym(a.get("keys"))
        await p.keyboard.down(combo)
        await asyncio.sleep(max(0, int(a.get("amount") or 1000)) / 1000)
        await p.keyboard.up(combo)

    elif t == "scroll":
        amount = max(1, abs(int(a.get("amount") or 3)))
        step = amount * 120
        dx, dy = {
            "down": (0, step),
            "up": (0, -step),
            "right": (step, 0),
            "left": (-step, 0),
        }.get(a.get("direction") or "down", (0, step))
        await p.mouse.move(x if x is not None else 640, y if y is not None else 360)
        await p.mouse.wheel(dx, dy)

    elif t == "goto":
        await p.goto(a.get("url") or "about:blank", wait_until="domcontentloaded", timeout=20000)

    elif t == "click_element":
        loc = p.locator(f'[data-cua-id="{int(a["element_id"])}"]').first
        await loc.click(timeout=5000)

    elif t == "type_element":
        loc = p.locator(f'[data-cua-id="{int(a["element_id"])}"]').first
        await loc.fill(a.get("text") or "", timeout=5000)
        if a.get("submit"):
            await loc.press("Enter", timeout=5000)

    elif t == "wait":
        await asyncio.sleep(max(0, int(a.get("amount") or 500)) / 1000)

    elif t in ("screenshot", "cursor_position", "finish"):
        pass

    else:
        raise ValueError(f"unsupported action: {t}")


class ObserveIn(BaseModel):
    mode: str = "pixel"


class ActIn(BaseModel):
    action: dict


class ExecIn(BaseModel):
    cmd: str


class EvalIn(BaseModel):
    expr: str


@app.get("/health")
def health() -> dict:
    try:
        p = page()
        url = p.url
    except Exception:
        url = None
    png = STATE.get("png")
    w, h = Image.open(io.BytesIO(png)).size if png else (1280, 800)
    return {"ok": True, "env": "browser", "width": w, "height": h, "url": url}


@app.post("/observe")
async def observe(body: ObserveIn) -> dict:
    assert LOCK is not None
    async with LOCK:
        p = page()
        png, changed = await settle(p, STATE.get("png"))
        STATE["png"] = png
        w, h = Image.open(io.BytesIO(png)).size
        try:
            title = await p.title()
        except Exception:
            title = ""
        out = {
            "screenshot": base64.b64encode(png).decode(),
            "width": w,
            "height": h,
            "url": p.url,
            "title": title,
            "changed": changed,
        }
        if body.mode == "dom":
            data = await extract(p)
            out["elements"] = data.get("elements", [])
            out["url"] = data.get("url", p.url)
            out["title"] = data.get("title", title)
        return out


@app.post("/act")
async def act(body: ActIn) -> dict:
    assert LOCK is not None
    try:
        async with LOCK:
            await dispatch(page(), body.action)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to the trace
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}


@app.post("/eval")
async def evaluate(body: EvalIn) -> dict:
    assert LOCK is not None
    async with LOCK:
        try:
            return {"result": await page().evaluate(body.expr)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:500]}


@app.post("/exec")
def exec_cmd(body: ExecIn) -> dict:
    proc = subprocess.run(body.cmd, shell=True, capture_output=True, text=True, timeout=60)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
