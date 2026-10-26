"""Serve the trace directory so the viewer can fetch JSONL/PNGs (file:// would be blocked)."""

from __future__ import annotations

import shutil
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        pass


def serve(traces: Path, port: int = 8765, open_browser: bool = True) -> None:
    traces = Path(traces).resolve()
    traces.mkdir(parents=True, exist_ok=True)

    viewer = Path(__file__).resolve().parent.parent / "viewer" / "index.html"
    shutil.copyfile(viewer, traces / "index.html")
    if not (traces / "runs.json").exists():
        (traces / "runs.json").write_text("[]")

    handler = partial(_QuietHandler, directory=str(traces))
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"trace viewer: {url}")
    print(f"serving     : {traces}")
    if open_browser:
        webbrowser.open(url)
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
