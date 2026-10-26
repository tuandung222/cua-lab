# cua-lab

A small, inspectable harness for **computer-use agents (CUA)** and **browser-use
agents (BUA)**. One agent loop, two sandboxes, full traces you can replay frame
by frame.

The point is not to ship an agent framework. It is to make the parts you would
normally never see — the observation, the coordinate the model picked, the
action that did nothing, the 3 seconds of UI settling — visible.

```
            ┌──────────────────────────── host ────────────────────────────┐
            │  loop.py:  observe → policy.decide → act → observe → record  │
            │      │            │                       │                 │
            │      │        Anthropic API          traces/*.jsonl + PNGs   │
            │      ▼                                              │        │
            │  HttpEnv  ────────── HTTP ──────────┐               ▼        │
            └─────────────────────────────────────┼─────────  viewer/index  │
                                                  │                        │
        ┌─────────────────────────────────────────┴──────────────────────┐ │
        │ desktop container                    browser container         │ │
        │ Xvfb + openbox + tint2               Xvfb + Chromium (headful) │ │
        │ scrot  (screen in)                   page.screenshot()         │ │
        │ xdotool (mouse/key out)              Playwright over CDP       │ │
        │ noVNC :6080                          noVNC :6081               │ │
        └────────────────────────────────────────────────────────────────┘ │
```

Both containers expose the identical HTTP surface (`/observe`, `/act`,
`/exec`, `/eval`). The loop cannot tell them apart — which is exactly the
ablation: same model, same task, different observation and action space.

## Quickstart

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
uv sync
make up                       # builds both sandboxes (~3-5 min first time)
make doctor

# no API key needed: verifies sandbox + trace pipeline
make smoke-desktop
make smoke-browser
```

Watch a sandbox live while a task runs:

- desktop: http://localhost:6080/vnc.html?autoconnect=1&resize=scale
- browser: http://localhost:6081/vnc.html?autoconnect=1&resize=scale

Run a task, then replay it:

```bash
uv run cua-lab tasks
uv run cua-lab run --task tasks/desktop/d1_create_file.yaml
uv run cua-lab view           # http://127.0.0.1:8765
```

The viewer shows, per step: the screenshot before and after, a crosshair where
the model clicked, the raw model text, token usage, and the action result.

## The experiment that matters

Run the *same* browser task through both interfaces:

```bash
uv run cua-lab run --task tasks/browser/b1_form.yaml --obs dom
uv run cua-lab run --task tasks/browser/b1_form.yaml --obs pixel
```

`dom` gives the model a numbered list of elements and a `click(id)` action.
`pixel` gives it a screenshot and raw coordinates. Compare success rate, step
count, token usage, and — more interesting — *how* they fail. Typical pattern:
pixel mode fails on coordinate arithmetic and focus, dom mode fails on stale
element ids after a re-render.

Then push on the remaining knobs:

| knob | where | what it teaches |
|---|---|---|
| settle threshold / timeout | `envs/*/actuator.py` | how much of agent failure is just timing |
| screenshot resolution | `start.sh` (1280x800) | coordinate scaling and token cost |
| element filter | `DOM_JS` in `envs/browser/actuator.py` | what "structure" the model actually gets |
| history | `policy/anthropic_policy.py` | old screenshots replaced by a text placeholder (`CUA_KEEP_IMAGES=1` keeps them) |
| action granularity | `_normalize()` | low-level HID vs semantic actions |

## Layout

```
cua_lab/
  loop.py              the agent loop (~60 lines)
  env.py               HTTP client for both actuators
  policy/              anthropic_policy.py (CUA + BUA tools), scripted.py
  trace/               recorder.py (JSONL + PNGs), server.py (viewer host)
  viewer/index.html    single-file replay UI
envs/
  desktop/             Xvfb + openbox + tint2 + xdotool + scrot + noVNC
  browser/             Chromium + Playwright/CDP + local static site
tasks/                 YAML: instruction + verifier, one file per task
traces/                output: one directory per run (gitignored)
```

## The API surface (it moves)

The pixel policy targets the GA computer toolset
`computer_toolset_20260801`; the action names are tool names (`left_click`,
`type`, `key`, ...). Anthropic has changed this surface repeatedly, so the
version and model are configurable:

```bash
CUA_TOOL=computer_toolset_20260801   # or the legacy computer_20250124
CUA_MODEL=claude-sonnet-5-5
```

If a run fails with an unknown tool or action, dump the first response
(`traces/<run>/steps.jsonl`, field `raw` was written by the policy — add
`--tool` to try the legacy shape) and adjust `_normalize()` in
`cua_lab/policy/anthropic_policy.py`. Everything the model emits is recorded
verbatim, so you are never guessing.

The DOM policy does not use a computer tool at all: it defines a custom
`browser` tool with `goto / click / type / scroll / key / finish`. That is the
real difference between a CUA and a BUA at the protocol level.

## Things that will bite you (on purpose)

- **Coordinate space.** The screenshot the model sees is 1280×800 (desktop) or
  the Chromium viewport. Clicks are in that space. Any resize step must be
  undone before the action reaches X11/Playwright.
- **Settling.** A screenshot taken 100 ms after a click catches animations and
  menus mid-draw. The actuators diff consecutive frames until the screen is
  quiet; tune `eps`/`timeout` and watch failures change.
- **Focus and text input.** `xdotool type` sends keystrokes to the focused
  window. If the click missed, text goes nowhere and the next screenshot looks
  unchanged — a very common silent failure.
- **DOM ids are per-observation.** The browser actuator renumbers elements
  every step. A model that caches an id across a re-render clicks the wrong
  node.
- **Viewport clipping.** Only elements intersecting the viewport are listed, so
  the scroll task cannot be solved without scrolling.
- **Arm64.** Both images are `debian:bookworm-slim`; Chromium/X11/Playwright all
  have arm64 builds. Docker Desktop must be running.

## Not included (v1)

Deliberately out of scope for now: prompt-injection payloads, taint tracking,
human-in-the-loop confirmation for irreversible actions, AT-SPI accessibility
tree on the desktop side, and multi-task benchmark scores. The sandbox is
network-isolated from your host except for the exposed ports, but it is *not* a
security boundary — do not put real credentials inside.
