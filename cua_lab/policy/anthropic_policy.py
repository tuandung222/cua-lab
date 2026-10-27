"""Anthropic policy adapter.

Two very different tool surfaces are exposed here on purpose:

* pixel mode -> the GA computer toolset. The model sees a screenshot and emits
  low-level actions (left_click, type, key, scroll ...). This is a CUA.
* dom mode   -> a custom `browser` tool. The model sees a numbered list of
  interactive elements and emits click(id) / type(id). This is a BUA.

Same loop, same model, different observation and action space. Comparing the
two on identical tasks is the reason this repo exists.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import anthropic

from ..types import Action, Decision, Observation, Task
from .base import PolicyError

CURRENT_TOOL = "computer_toolset_20260801"
LEGACY_TOOL = "computer_20250124"
FUNCTION_TOOL = "function"

DESKTOP_SYSTEM = """You are an agent controlling a Linux desktop through a computer-use tool.

Rules:
- The screenshot is exactly {w}x{h} pixels. Coordinates are pixel positions on that image, origin at top-left.
- Act one step at a time; the next screenshot shows the result of your action.
- Always click an input field or window to focus it before calling `type`.
- Prefer keyboard input over mouse when it is more reliable (e.g. typing a path in a dialog).
- Never ask the user questions and never explain in prose. Call a tool.
- When the task is complete, reply with one short sentence and no tool call (or call action=finish).
"""

BROWSER_SYSTEM = """You are an agent controlling a Chromium browser through a structured browser tool.

Rules:
- Each observation lists interactive elements as: [id] tag "label" @ (x, y)
- Element ids are reassigned on every observation. Only use ids from the latest list.
- Prefer element ids over coordinates. Use `goto` when opening a known URL is simpler.
- After typing into a field you may pass submit=true to press Enter.
- When the task is complete, call action=finish with a short note.
"""

BROWSER_TOOL: dict[str, Any] = {
    "name": "browser",
    "description": (
        "Control the browser. Element ids come from the most recent observation. "
        "Actions: goto, click, type, scroll, key, wait, finish."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["goto", "click", "type", "scroll", "key", "wait", "finish"],
            },
            "element_id": {"type": "integer", "description": "Target element id from the latest observation."},
            "text": {"type": "string", "description": "Text to type, or a key combo like 'ctrl+a'."},
            "url": {"type": "string", "description": "Absolute or relative URL for goto."},
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "integer", "description": "Scroll amount in wheel notches."},
            "duration": {"type": "number", "description": "Wait duration in seconds."},
            "submit": {"type": "boolean", "description": "Press Enter after typing."},
            "note": {"type": "string", "description": "One short sentence of reasoning."},
        },
        "required": ["action"],
    },
}

COMPUTER_FUNCTION_TOOL: dict[str, Any] = {
    "name": "computer",
    "description": (
        "Control the screen using pixel coordinates (x, y) on the latest screenshot. "
        "Actions: left_click, double_click, right_click, mouse_move, left_click_drag, type, key, scroll, wait, screenshot, finish."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "left_click",
                    "double_click",
                    "right_click",
                    "mouse_move",
                    "left_click_drag",
                    "type",
                    "key",
                    "scroll",
                    "wait",
                    "screenshot",
                    "finish",
                ],
            },
            "coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[x, y] pixel coordinates on the screenshot (origin at top-left).",
            },
            "start_coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[x, y] start coordinates for left_click_drag.",
            },
            "text": {
                "type": "string",
                "description": "Text to type (for action=type) or key combo like 'Return' or 'ctrl+s' (for action=key).",
            },
            "scroll_direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "scroll_amount": {"type": "integer", "description": "Scroll amount in wheel notches."},
            "duration": {"type": "number", "description": "Wait duration in seconds."},
            "note": {"type": "string", "description": "One short sentence of reasoning."},
        },
        "required": ["action"],
    },
}


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode()


def _image_block(png: bytes) -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(png)}}


def _dom_text(obs: Observation) -> str:
    lines = [f"URL: {obs.url}", f"Title: {obs.title}", "Interactive elements:"]
    for e in obs.elements or []:
        kind = str(e.get("tag", "?"))
        if e.get("type"):
            kind += f"[{e['type']}]"
        label = str(e.get("label") or "").replace('"', "'")[:60]
        lines.append(f'[{e["id"]}] {kind} "{label}" @ ({e["x"]},{e["y"]})')
    if not obs.elements:
        lines.append("(none visible)")
    return "\n".join(lines)


def _usage(resp: Any) -> dict[str, Any]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    data = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    return {k: v for k, v in data.items() if isinstance(v, (int, float))}


class AnthropicPolicy:
    name = "anthropic"

    def __init__(
        self,
        mode: str = "pixel",
        model: str | None = None,
        tool: str | None = None,
        beta: str | None = None,
        max_tokens: int = 1024,
    ):
        try:
            self.client = anthropic.Anthropic()
        except Exception as exc:  # missing key, bad config
            raise PolicyError(
                f"cannot create Anthropic client: {exc}\n"
                "Set ANTHROPIC_API_KEY (put it in .env and `set -a; source .env; set +a`)."
            ) from exc

        self.mode = mode
        self.model = model or os.environ.get("CUA_MODEL", "claude-sonnet-5-5")
        is_claude = "claude" in self.model.lower()
        default_tool = os.environ.get("CUA_TOOL", CURRENT_TOOL) if is_claude else FUNCTION_TOOL
        self.tool = tool or default_tool
        self.beta = beta or (
            os.environ.get("CUA_ANTHROPIC_BETA") or ("computer-use-2025-01-24" if self.tool == LEGACY_TOOL else None)
            if is_claude
            else None
        )
        self.max_tokens = max_tokens
        self.keep_images = os.environ.get("CUA_KEEP_IMAGES", "0") == "1"

        self._messages: list[dict[str, Any]] = []
        self._pending: list[tuple[Any, Action]] = []
        self._started = False
        self._tools: list[dict[str, Any]] = []
        self._obs: Observation | None = None

    # ---------------------------------------------------------------- public

    def decide(
        self,
        task: Task,
        obs: Observation,
        results: list[dict[str, Any]] | None = None,
    ) -> Decision:
        self._obs = obs
        if not self._started:
            self._started = True
            self._tools = self._build_tools(obs)
            content: list[dict[str, Any]] = [{"type": "text", "text": self._opening_text(task, obs)}]
            if self.mode == "dom":
                content.append({"type": "text", "text": _dom_text(obs)})
            content.append(_image_block(obs.screenshot))
            self._messages.append({"role": "user", "content": content})
        else:
            self._messages.append({"role": "user", "content": self._tool_results(obs, results)})

        resp = self._call()
        return self._parse(resp)

    # --------------------------------------------------------------- private

    def _opening_text(self, task: Task, obs: Observation) -> str:
        head = f"Task: {task.instruction}"
        if self.mode == "pixel":
            return head + f"\n\nThe screenshot is {obs.width}x{obs.height} px; coordinates are in that space."
        return head

    def _build_tools(self, obs: Observation) -> list[dict[str, Any]]:
        if self.mode == "dom":
            return [BROWSER_TOOL]
        if self.tool == FUNCTION_TOOL:
            return [COMPUTER_FUNCTION_TOOL]
        if self.tool == LEGACY_TOOL:
            return [
                {
                    "type": LEGACY_TOOL,
                    "name": "computer",
                    "display_width_px": obs.width,
                    "display_height_px": obs.height,
                    "display_number": 1,
                }
            ]
        return [{"type": self.tool}]

    def _tool_results(
        self,
        obs: Observation,
        act_results: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        out = []
        for idx, (block, action) in enumerate(self._pending):
            last = idx == len(self._pending) - 1
            res = act_results[idx] if act_results and idx < len(act_results) else {}
            failed = res.get("ok") is False
            err_msg = f"Action failed: {res.get('error', 'unknown error')}" if failed else None

            info_lines: list[str] = []
            if err_msg:
                info_lines.append(err_msg)
            if action.type == "cursor_position" and obs.cursor:
                info_lines.append(f"Cursor position: ({obs.cursor.get('x')}, {obs.cursor.get('y')})")

            if last:
                if self.mode == "dom":
                    info_lines.append("New observation.\n" + _dom_text(obs))
                else:
                    status = "New screenshot."
                    if obs.changed is False and action.type not in (
                        "screenshot",
                        "cursor_position",
                        "wait",
                        "finish",
                    ):
                        status += " (screen pixels did not change)"
                    info_lines.append(status)
                content: list[dict[str, Any]] = [
                    {"type": "text", "text": "\n".join(info_lines)},
                    _image_block(obs.screenshot),
                ]
            else:
                content = [{"type": "text", "text": "\n".join(info_lines) or "ok"}]

            item: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": content}
            if failed:
                item["is_error"] = True
            out.append(item)
        self._pending = []
        return out

    def _system(self, obs: Observation) -> str:
        if self.mode == "dom":
            return BROWSER_SYSTEM
        return DESKTOP_SYSTEM.format(w=obs.width, h=obs.height)

    def _call(self) -> Any:
        if not self.keep_images:
            self._strip_old_images()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._system(self._obs),
            "tools": self._tools,
            "messages": self._messages,
        }
        if self.beta:
            kwargs["extra_headers"] = {"anthropic-beta": self.beta}
        try:
            return self.client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            raise PolicyError(f"Anthropic API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - bad tool shape, auth, network
            raise PolicyError(f"{type(exc).__name__}: {exc}") from exc

    def _strip_old_images(self) -> None:
        """Keep only the newest screenshot.

        Every step adds ~1.5k image tokens to the message history. Dropping old
        frames is the standard trade: the model reasons from the current screen
        plus the textual action log, not from a gallery of past screens.
        Set CUA_KEEP_IMAGES=1 to keep the full visual history instead.
        """
        for msg in self._messages[:-1]:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image":
                    block.clear()
                    block.update({"type": "text", "text": "[previous screenshot omitted]"})

    def _parse(self, resp: Any) -> Decision:
        texts: list[str] = []
        actions: list[Action] = []
        pending: list[tuple[Any, Action]] = []

        for block in resp.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "tool_use":
                action = self._normalize(block.name, dict(block.input or {}))
                if action.type == "unknown":
                    raise PolicyError(
                        f"unrecognized tool_use name={block.name!r} input={dict(block.input or {})!r}. "
                        "Gateways that proxy Anthropic models sometimes flatten the typed computer "
                        "tool into a nameless function; try CUA_TOOL=computer_20250124 with "
                        "CUA_ANTHROPIC_BETA=computer-use-2025-01-24, or use the function-tool variant."
                    )
                pending.append((block, action))
                actions.append(action)

        self._pending = pending
        self._messages.append(
            {"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]}
        )

        raw = {
            "stop_reason": resp.stop_reason,
            "content": [b.model_dump(exclude_none=True) for b in resp.content],
        }
        return Decision(
            actions=actions,
            text="\n".join(t for t in texts if t) or None,
            raw=raw,
            usage=_usage(resp),
            stop_reason=resp.stop_reason,
        )

    def _normalize(self, name: str, inp: dict[str, Any]) -> Action:
        n = (name or "").lower()
        if n in ("computer", "browser", "computer_toolset_20260801", LEGACY_TOOL):
            # Some gateways relay the legacy tool with `type` instead of `action`.
            n = (inp.pop("action", "") or inp.pop("type", "") or "").lower()

        coord = inp.get("coordinate") or [None, None]
        x, y = (list(coord) + [None, None])[:2]
        # Gateways that re-serialize the computer tool sometimes rename `text`
        # to `value` or `key`/`keys`; accept all spellings.
        text = inp.get("text") or inp.get("value") or inp.get("key") or inp.get("keys") or ""
        note = inp.get("note")

        if n in ("left_click", "click"):
            if inp.get("element_id") is not None:
                return Action("click_element", element_id=int(inp["element_id"]), note=note)
            return Action("click", x=x, y=y, keys=text or None, note=note)
        if n == "right_click":
            return Action("right_click", x=x, y=y, keys=text or None, note=note)
        if n == "middle_click":
            return Action("middle_click", x=x, y=y, note=note)
        if n == "double_click":
            return Action("double_click", x=x, y=y, note=note)
        if n == "triple_click":
            return Action("triple_click", x=x, y=y, note=note)
        if n == "mouse_move":
            return Action("move", x=x, y=y, note=note)
        if n == "left_click_drag":
            start = inp.get("start_coordinate") or [x, y]
            sx, sy = (list(start) + [None, None])[:2]
            return Action("drag", x=sx, y=sy, to_x=x, to_y=y, note=note)
        if n == "left_mouse_down":
            return Action("mousedown", x=x, y=y, note=note)
        if n == "left_mouse_up":
            return Action("mouseup", x=x, y=y, note=note)
        if n == "scroll":
            return Action(
                "scroll",
                x=x,
                y=y,
                direction=inp.get("scroll_direction") or inp.get("direction") or "down",
                amount=int(inp.get("scroll_amount") or inp.get("amount") or 3),
                note=note,
            )
        if n == "type":
            if inp.get("element_id") is not None:
                return Action(
                    "type_element",
                    element_id=int(inp["element_id"]),
                    text=text,
                    submit=bool(inp.get("submit")),
                    note=note,
                )
            return Action("type", text=text, note=note)
        if n == "key":
            return Action("key", keys=text, amount=int(inp.get("repeat") or 1), note=note)
        if n == "hold_key":
            dur = inp.get("duration") or inp.get("amount") or 1
            return Action("hold_key", keys=text, amount=int(float(dur) * 1000), note=note)
        if n == "wait":
            dur = inp.get("duration") or inp.get("amount") or 1
            return Action("wait", amount=int(float(dur) * 1000), note=note)
        if n == "screenshot":
            return Action("screenshot", note=note)
        if n == "cursor_position":
            return Action("cursor_position", note=note)
        if n == "goto":
            return Action("goto", url=inp.get("url", ""), note=note)
        if n == "finish":
            return Action("finish", note=note)
        if n == "zoom":
            return Action("zoom", x=x, y=y, note="zoom is not implemented in this harness")
        return Action(n or "unknown", note=str(inp)[:200])
