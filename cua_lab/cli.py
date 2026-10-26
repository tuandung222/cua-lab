from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .env import EnvError, HttpEnv
from .loop import run
from .policy.base import PolicyError
from .tasks import list_tasks, load_task
from .trace.recorder import Recorder
from .trace.server import serve
from .types import Action

ENV_URLS = {
    "desktop": "http://127.0.0.1:8001",
    "browser": "http://127.0.0.1:8002",
}
LIVE_VIEW = {
    "desktop": "http://localhost:6080/vnc.html?autoconnect=1&resize=scale",
    "browser": "http://localhost:6081/vnc.html?autoconnect=1&resize=scale",
}


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader; real environment always wins."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.split(" #")[0].strip().strip("'\"")
        if key and val and key not in os.environ:
            os.environ[key] = val


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cua-lab", description="Minimal CUA / BUA harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one task in a sandbox")
    r.add_argument("--task", required=True, help="path to a task YAML")
    r.add_argument("--env", choices=sorted(ENV_URLS), help="override task env")
    r.add_argument("--obs", choices=["pixel", "dom"], help="observation interface")
    r.add_argument("--policy", choices=["api", "script"], default="api")
    r.add_argument("--model", default=None, help="Claude model id")
    r.add_argument("--tool", default=None, help="computer tool type (default: GA toolset)")
    r.add_argument("--url", default=None, help="actuator base url")
    r.add_argument("--max-steps", type=int, default=None)
    r.add_argument("--traces", default="traces")

    v = sub.add_parser("view", help="serve the trace viewer")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--traces", default="traces")
    v.add_argument("--no-open", action="store_true")

    t = sub.add_parser("tasks", help="list task files")
    t.add_argument("--root", default="tasks")

    sub.add_parser("doctor", help="check sandboxes and credentials")
    return p


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "view":
        serve(Path(args.traces), args.port, open_browser=not args.no_open)
        return 0
    if args.cmd == "tasks":
        for path in list_tasks(args.root):
            try:
                task = load_task(path)
                print(f"{task.id:22} env={task.env:8} obs={task.obs or '-':6} steps={task.max_steps:3}  {path}")
            except Exception as exc:  # noqa: BLE001
                print(f"INVALID {path}: {exc}")
        return 0
    if args.cmd == "doctor":
        return cmd_doctor()
    return 1


def cmd_run(args) -> int:
    task = load_task(args.task)
    env_name = args.env or task.env
    mode = args.obs or task.obs or ("dom" if env_name == "browser" else "pixel")
    url = args.url or ENV_URLS[env_name]
    max_steps = args.max_steps or task.max_steps

    env = HttpEnv(env_name, url, mode)
    try:
        health = env.health()
    except EnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.policy == "script":
        from .policy.scripted import ScriptedPolicy

        if not task.script:
            print(f"error: task {task.id} has no `script:` block", file=sys.stderr)
            return 2
        policy = ScriptedPolicy([Action(**a) for a in task.script])
    else:
        from .policy.anthropic_policy import AnthropicPolicy

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("warning: ANTHROPIC_API_KEY is not set (the SDK may still find a key elsewhere)")
        try:
            policy = AnthropicPolicy(mode=mode, model=args.model, tool=args.tool)
        except PolicyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    rec = Recorder(
        Path(args.traces),
        {
            "task": task.id,
            "env": env_name,
            "mode": mode,
            "model": getattr(policy, "model", "script"),
            "instruction": task.instruction,
            "screen": f"{health.get('width')}x{health.get('height')}",
        },
    )

    print(f"task      : {task.id}  ({env_name})")
    print(f"interface : {mode}  [{health.get('width')}x{health.get('height')}]")
    print(f"model     : {getattr(policy, 'model', 'script')}")
    print(f"live view : {LIVE_VIEW[env_name]}")
    print(f"trace     : {rec.dir}")
    print()

    try:
        ok, detail = run(task, env, policy, rec, max_steps)
    except PolicyError as exc:
        rec.finish(False, {"error": str(exc)})
        print(f"\npolicy error: {exc}", file=sys.stderr)
        return 1
    except EnvError as exc:
        rec.finish(False, {"error": str(exc)})
        print(f"\nenv error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - keep the trace even when the run dies
        rec.finish(False, {"error": f"{type(exc).__name__}: {exc}"})
        raise

    print()
    print(f"success : {'YES' if ok else 'NO'}   steps: {rec.n}")
    print(f"verify  : {detail}")
    print(f"trace   : {rec.dir}")
    print(f"replay  : uv run cua-lab view   ->  http://127.0.0.1:8765/")
    return 0 if ok else 1


def cmd_doctor() -> int:
    problems = 0
    print(f"python    : {sys.version.split()[0]}")
    print(f"api key   : {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'MISSING'}")
    print(f"base url  : {os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com')}")
    print(f"model     : {os.environ.get('CUA_MODEL', '(policy default)')}")
    print(f"tool      : {os.environ.get('CUA_TOOL', 'computer_toolset_20260801')}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems += 1

    for name, url in ENV_URLS.items():
        try:
            h = HttpEnv(name, url).health()
            print(f"{name:9} : ok   {url}  {h.get('width')}x{h.get('height')}  live={LIVE_VIEW[name]}")
        except EnvError as exc:
            problems += 1
            print(f"{name:9} : DOWN {url}\n            {exc}")

    traces = Path("traces")
    traces.mkdir(exist_ok=True)
    probe = traces / ".write-probe"
    try:
        probe.write_text("ok")
        probe.unlink()
        print("traces    : writable")
    except OSError as exc:
        problems += 1
        print(f"traces    : NOT writable ({exc})")

    print()
    print("ok" if problems == 0 else f"{problems} problem(s) — is Docker running? `make up`")
    return 0 if problems == 0 else 1
