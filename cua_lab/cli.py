from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .benchmarks import BenchmarkRegistry
from .env import EnvError, HttpEnv
from .loop import run
from .policy.base import PolicyError
from .tasks import list_tasks, load_task
from .trace.recorder import Recorder
from .trace.server import serve
from .types import Action, Task

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
    p = argparse.ArgumentParser(prog="cua-lab", description="Minimal CUA / BUA harness & VPI benchmark suite")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one task (YAML path or benchmark:case_id) in a sandbox")
    r.add_argument("--task", required=True, help="path to a task YAML or vpi_bench:<case_id>")
    r.add_argument("--env", choices=sorted(ENV_URLS), help="override task env")
    r.add_argument("--obs", choices=["pixel", "dom"], help="observation interface")
    r.add_argument("--policy", choices=["api", "script"], default="api")
    r.add_argument("--model", default=None, help="model id")
    r.add_argument("--tool", default=None, help="computer tool type (default: GA toolset)")
    r.add_argument("--url", default=None, help="actuator base url")
    r.add_argument("--max-steps", type=int, default=None)
    r.add_argument("--traces", default="traces")
    r.add_argument("--cache-dir", default="benchmarks_data")
    r.add_argument("--no-reset", action="store_true", help="keep sandbox state from previous run")

    b = sub.add_parser("bench", help="manage and run external VPI benchmarks (e.g. vpi_bench)")
    bsub = b.add_subparsers(dest="bench_cmd", required=True)

    bsync = bsub.add_parser("sync", help="download benchmark dataset and web platform assets")
    bsync.add_argument("--benchmark", default="vpi_bench", choices=BenchmarkRegistry.names())
    bsync.add_argument("--cache-dir", default="benchmarks_data")

    blist = bsub.add_parser("list", help="list benchmark test cases")
    blist.add_argument("--benchmark", default="vpi_bench", choices=BenchmarkRegistry.names())
    blist.add_argument("--mode", choices=["computer_use", "browser_use"], default=None)
    blist.add_argument("--platform", default=None, help="e.g. amazon, bbc, booking, email, messenger")
    blist.add_argument("--search", default=None, help="filter substring")
    blist.add_argument("--limit", type=int, default=50)
    blist.add_argument("--cache-dir", default="benchmarks_data")

    brun = bsub.add_parser("run", help="run a single benchmark testcase")
    brun.add_argument("--case", required=True, help="case id or uid (e.g. amazon_filedel_api)")
    brun.add_argument("--benchmark", default="vpi_bench", choices=BenchmarkRegistry.names())
    brun.add_argument("--model", default=None)
    brun.add_argument("--tool", default=None)
    brun.add_argument("--max-steps", type=int, default=18)
    brun.add_argument("--traces", default="traces")
    brun.add_argument("--cache-dir", default="benchmarks_data")
    brun.add_argument("--remote-web", action="store_true", help="use github.io URLs instead of local :8081")

    beval = bsub.add_parser("eval", help="evaluate a batch of benchmark testcases and report AR / SR")
    beval.add_argument("--benchmark", default="vpi_bench", choices=BenchmarkRegistry.names())
    beval.add_argument("--mode", choices=["computer_use", "browser_use"], default=None)
    beval.add_argument("--platform", default=None)
    beval.add_argument("--search", default=None)
    beval.add_argument("--limit", type=int, default=5)
    beval.add_argument("--model", default=None)
    beval.add_argument("--tool", default=None)
    beval.add_argument("--max-steps", type=int, default=18)
    beval.add_argument("--traces", default="traces")
    beval.add_argument("--cache-dir", default="benchmarks_data")
    beval.add_argument("--remote-web", action="store_true")

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
    if os.environ.get("CUA_DESKTOP_URL"):
        ENV_URLS["desktop"] = os.environ["CUA_DESKTOP_URL"]
    if os.environ.get("CUA_BROWSER_URL"):
        ENV_URLS["browser"] = os.environ["CUA_BROWSER_URL"]
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "bench":
        return cmd_bench(args)
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


def _resolve_task_arg(task_arg: str, cache_dir: str = "benchmarks_data", max_steps: int | None = None) -> Task:
    if ":" in task_arg and not Path(task_arg).exists():
        bench_name, case_id = task_arg.split(":", 1)
        adapter = BenchmarkRegistry.get(bench_name)
        case = adapter.get_case(Path(cache_dir), case_id)
        return adapter.to_task(case, max_steps=max_steps or 18)
    return load_task(task_arg)


def execute_task(
    task: Task,
    *,
    env_override: str | None = None,
    obs_override: str | None = None,
    policy_kind: str = "api",
    model: str | None = None,
    tool: str | None = None,
    url_override: str | None = None,
    max_steps_override: int | None = None,
    traces_dir: str = "traces",
    no_reset: bool = False,
) -> tuple[bool, dict, Recorder]:
    env_name = env_override or task.env
    mode = obs_override or task.obs or ("dom" if env_name == "browser" else "pixel")
    url = url_override or ENV_URLS[env_name]
    max_steps = max_steps_override or task.max_steps

    env = HttpEnv(env_name, url, mode)
    health = env.health()
    if not no_reset:
        env.reset()
    if task.setup:
        env.exec_shell(task.setup)
    for inst in task.setup_instructions or []:
        inst.execute(env)

    if policy_kind == "script":
        from .policy.scripted import ScriptedPolicy

        if not task.script:
            raise PolicyError(f"task {task.id} has no `script:` block")
        policy = ScriptedPolicy([Action(**a) for a in task.script])
    else:
        from .policy.anthropic_policy import AnthropicPolicy

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("warning: ANTHROPIC_API_KEY is not set (the SDK may still find a key elsewhere)")
        policy = AnthropicPolicy(mode=mode, model=model, tool=tool)

    rec = Recorder(
        Path(traces_dir),
        {
            "task": task.id,
            "benchmark": task.benchmark,
            "platform": task.platform,
            "env": env_name,
            "mode": mode,
            "model": getattr(policy, "model", "script"),
            "instruction": task.instruction,
            "attacker_objective": task.attacker_objective,
            "screen": f"{health.get('width')}x{health.get('height')}",
        },
    )

    print(f"task      : {task.id}  ({env_name})")
    if task.benchmark:
        print(f"benchmark : {task.benchmark}  [platform={task.platform}]")
    if task.attacker_objective:
        print(f"objective : {task.attacker_objective}")
    print(f"interface : {mode}  [{health.get('width')}x{health.get('height')}]")
    print(f"model     : {getattr(policy, 'model', 'script')}")
    print(f"live view : {LIVE_VIEW[env_name]}")
    print(f"trace     : {rec.dir}")
    print()

    try:
        ok, detail = run(task, env, policy, rec, max_steps)
    except Exception as exc:
        rec.finish(False, {"error": f"{type(exc).__name__}: {exc}"})
        raise

    print()
    print(f"success   : {'YES' if ok else 'NO'}   steps: {rec.n}")
    if "attempted" in detail:
        print(f"attempted : {'YES (AR=1)' if detail['attempted'] else 'NO  (AR=0)'}")
    if "hijacked" in detail:
        print(f"hijacked  : {'YES (SR=1 — fooled by visual prompt injection!)' if detail['hijacked'] else 'NO  (SR=0)'}")
    if detail.get("explanation"):
        print(f"judge     : {detail['explanation']}")
    print(f"trace     : {rec.dir}")
    print(f"replay    : uv run cua-lab view   ->  http://127.0.0.1:8765/")
    return ok, detail, rec


def cmd_run(args) -> int:
    try:
        task = _resolve_task_arg(args.task, cache_dir=args.cache_dir, max_steps=args.max_steps)
        ok, _, _ = execute_task(
            task,
            env_override=args.env,
            obs_override=args.obs,
            policy_kind=args.policy,
            model=args.model,
            tool=args.tool,
            url_override=args.url,
            max_steps_override=args.max_steps,
            traces_dir=args.traces,
            no_reset=args.no_reset,
        )
        return 0 if ok else 1
    except (EnvError, PolicyError, KeyError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def cmd_bench(args) -> int:
    adapter = BenchmarkRegistry.get(args.benchmark)
    cache_dir = Path(args.cache_dir)

    if args.bench_cmd == "sync":
        info = adapter.sync_assets(cache_dir)
        print(f"synced benchmark : {info['benchmark']}")
        print(f"dataset dir      : {info['dataset_dir']}")
        print(f"web dir          : {info['web_dir']}")
        print(f"total cases      : {info['total_cases']}")
        return 0

    if args.bench_cmd == "list":
        cases = adapter.list_cases(
            cache_dir,
            mode=args.mode,
            platform=args.platform,
            search=args.search,
        )
        print(f"matching cases: {len(cases)} (showing up to {args.limit})")
        for c in cases[: args.limit]:
            print(f"{c.uid:48} mode={c.mode:12} platform={c.platform:9} obj={c.attacker_objective[:55]}")
        return 0

    if args.bench_cmd == "run":
        case = adapter.get_case(cache_dir, args.case)
        task = adapter.to_task(
            case,
            use_local_web=not args.remote_web,
            max_steps=args.max_steps,
        )
        ok, _, _ = execute_task(
            task,
            model=args.model,
            tool=args.tool,
            max_steps_override=args.max_steps,
            traces_dir=args.traces,
        )
        return 0 if ok else 1

    if args.bench_cmd == "eval":
        cases = adapter.list_cases(
            cache_dir,
            mode=args.mode,
            platform=args.platform,
            search=args.search,
        )[: args.limit]
        if not cases:
            print("no matching cases found.")
            return 1
        n_total = len(cases)
        n_user_ok = 0
        n_attempted = 0
        n_hijacked = 0
        for idx, case in enumerate(cases, start=1):
            print(f"\n=== [{idx}/{n_total}] {case.uid} ===")
            task = adapter.to_task(
                case,
                use_local_web=not args.remote_web,
                max_steps=args.max_steps,
            )
            ok, detail, _ = execute_task(
                task,
                model=args.model,
                tool=args.tool,
                max_steps_override=args.max_steps,
                traces_dir=args.traces,
            )
            if ok:
                n_user_ok += 1
            if detail.get("attempted") or detail.get("hijacked"):
                n_attempted += 1
            if detail.get("hijacked"):
                n_hijacked += 1

        print("\n" + "=" * 60)
        print(f"BENCHMARK SUMMARY ({adapter.name}) — {n_total} cases")
        print(f"  User Task Success : {n_user_ok}/{n_total} ({100*n_user_ok/n_total:.1f}%)")
        print(f"  Attempted Rate AR : {n_attempted}/{n_total} ({100*n_attempted/n_total:.1f}%)")
        print(f"  Hijacked  Rate SR : {n_hijacked}/{n_total} ({100*n_hijacked/n_total:.1f}%)")
        print("=" * 60)
        return 0

    return 1


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
