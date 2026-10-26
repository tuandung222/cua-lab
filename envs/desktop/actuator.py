"""Desktop actuator: X11 screen in, mouse/keyboard out.

Kept deliberately dumb. All agent logic lives on the host, so this process is
just a remote pair of hands (plus a settle check, which the host cannot do
cheaply over HTTP).
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import threading
import time

from fastapi import FastAPI
from PIL import Image, ImageChops, ImageStat
from pydantic import BaseModel

DISPLAY = os.environ.get("DISPLAY", ":99")
ENV = {**os.environ, "DISPLAY": DISPLAY}

app = FastAPI(title="cua-lab desktop actuator")
_LOCK = threading.Lock()
STATE: dict = {"png": None}

WIDTH, HEIGHT = 1280, 800


def shot() -> bytes:
    subprocess.run(["scrot", "-o", "/tmp/_shot.png"], env=ENV, check=True, timeout=10)
    with open("/tmp/_shot.png", "rb") as fh:
        return fh.read()


def _diff(a: bytes, b: bytes) -> float:
    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return 255.0
    stat = ImageStat.Stat(ImageChops.difference(ia, ib))
    return sum(stat.mean) / 3.0


def settle(prev: bytes | None, timeout: float = 3.0, interval: float = 0.12, quiet: int = 2, eps: float = 0.4):
    """Wait until the screen stops moving.

    A fixed sleep is either too short (animations) or too slow (every step).
    Frame diffing is the honest version of "wait for the UI".
    """
    cur = prev if prev is not None else shot()
    stable = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(interval)
        nxt = shot()
        delta = _diff(cur, nxt)
        cur = nxt
        stable = stable + 1 if delta < eps else 0
        if stable >= quiet:
            break
    changed = prev is not None and _diff(prev, cur) > 0.3
    return cur, changed


def xdo(*args) -> None:
    subprocess.run(["xdotool", *[str(a) for a in args]], env=ENV, check=True, timeout=10)


def cursor() -> dict:
    out = subprocess.run(
        ["xdotool", "getmouselocation", "--shell"], env=ENV, capture_output=True, text=True, timeout=5
    ).stdout
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"x": int(fields.get("X", 0)), "y": int(fields.get("Y", 0))}


def _require_xy(x, y) -> None:
    if x is None or y is None:
        raise ValueError("this action needs x and y")


def _mods(keys: str | None) -> list[str]:
    return [m for m in (keys or "").replace(" ", "+").split("+") if m]


def _click(x, y, count: int = 1, keys: str | None = None, button: int = 1) -> None:
    _require_xy(x, y)
    held = _mods(keys)
    for m in held:
        xdo("keydown", m)
    try:
        xdo("mousemove", x, y)
        xdo("click", "--repeat", count, "--delay", 80, button)
    finally:
        for m in reversed(held):
            xdo("keyup", m)


def _drag(x, y, tx, ty) -> None:
    _require_xy(x, y)
    _require_xy(tx, ty)
    xdo("mousemove", x, y)
    xdo("mousedown", 1)
    steps = 12
    for i in range(1, steps + 1):
        xdo("mousemove", int(x + (tx - x) * i / steps), int(y + (ty - y) * i / steps))
        time.sleep(0.02)
    xdo("mouseup", 1)


def _scroll(x, y, direction: str, amount: int) -> None:
    button = {"up": 4, "down": 5, "left": 6, "right": 7}.get(direction, 5)
    a = abs(int(amount or 3))
    clicks = a if a <= 20 else max(1, round(a / 120))  # 120 px ~= one wheel notch
    clicks = min(clicks, 10)
    if x is not None and y is not None:
        xdo("mousemove", x, y)
    for _ in range(clicks):
        xdo("click", button)


def dispatch(a: dict) -> None:
    t = a.get("type")
    x, y = a.get("x"), a.get("y")

    if t == "click":
        _click(x, y, 1, a.get("keys"))
    elif t == "double_click":
        _click(x, y, 2, a.get("keys"))
    elif t == "triple_click":
        _click(x, y, 3, a.get("keys"))
    elif t == "right_click":
        _click(x, y, 1, a.get("keys"), button=3)
    elif t == "middle_click":
        _click(x, y, 1, a.get("keys"), button=2)
    elif t == "move":
        _require_xy(x, y)
        xdo("mousemove", x, y)
    elif t == "mousedown":
        _require_xy(x, y)
        xdo("mousemove", x, y)
        xdo("mousedown", 1)
    elif t == "mouseup":
        _require_xy(x, y)
        xdo("mousemove", x, y)
        xdo("mouseup", 1)
    elif t == "drag":
        _drag(x, y, a.get("to_x"), a.get("to_y"))
    elif t == "type":
        text = a.get("text") or ""
        if text:
            xdo("type", "--delay", 20, "--", text)
    elif t == "key":
        combo = a.get("keys") or ""
        for _ in range(max(1, int(a.get("amount") or 1))):
            xdo("key", combo)
    elif t == "hold_key":
        combo = a.get("keys") or ""
        xdo("keydown", combo)
        time.sleep(max(0, int(a.get("amount") or 1000)) / 1000)
        xdo("keyup", combo)
    elif t == "scroll":
        _scroll(x, y, a.get("direction") or "down", int(a.get("amount") or 3))
    elif t == "wait":
        time.sleep(max(0, int(a.get("amount") or 500)) / 1000)
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


@app.get("/health")
def health() -> dict:
    return {"ok": True, "env": "desktop", "width": WIDTH, "height": HEIGHT, "display": DISPLAY}


@app.post("/observe")
def observe(body: ObserveIn) -> dict:
    with _LOCK:
        png, changed = settle(STATE["png"])
        STATE["png"] = png
    w, h = Image.open(io.BytesIO(png)).size
    return {
        "screenshot": base64.b64encode(png).decode(),
        "width": w,
        "height": h,
        "changed": changed,
        "cursor": cursor(),
    }


@app.post("/act")
def act(body: ActIn) -> dict:
    try:
        dispatch(body.action)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surfaced to the trace
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}


@app.post("/exec")
def exec_cmd(body: ExecIn) -> dict:
    try:
        proc = subprocess.run(
            body.cmd, shell=True, capture_output=True, text=True, timeout=60, env=ENV
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "timeout"}


@app.post("/eval")
def eval_js() -> dict:
    return {"error": "not a browser"}
