"""HTTP server for `/srv/site` (:8080) with dynamic Cloud Drive workspace (`/drive/`).

Provides:
- Static file serving for `/srv/site` (existing cua-lab intranet pages).
- Dynamic Cloud Drive workspace at `/drive/index.html` backed by `/srv/site/drive_files`
  and mirrored to `/home/computeruse`, enabling full offline evaluation of VPI-Bench
  `browser_use` (`drive_*`, `email_preloaded_*`, `messenger_preloaded_*`) scenarios
  without requiring external Google account authentication.
- Request audit logging at `/tmp/vpi_web_requests.jsonl` for deterministic verification.
"""

from __future__ import annotations

import html
import http.server
import json
import os
import posixpath
import time
import urllib.parse
from pathlib import Path

SITE_ROOT = Path(os.environ.get("SITE_ROOT", "/srv/site"))
DRIVE_DIR = SITE_ROOT / "drive_files"
COMPUTERUSE_DIR = Path("/home/computeruse")
AUDIT_LOG = Path("/tmp/vpi_web_requests.jsonl")


def _log_event(event: dict) -> None:
    try:
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _sync_to_computeruse(filename: str, content: bytes | None) -> None:
    """Keep `/home/computeruse/<filename>` and `/home/computeruse/files/<filename>` in sync."""
    for base in (COMPUTERUSE_DIR, COMPUTERUSE_DIR / "files"):
        target = base / filename
        if content is None:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
        else:
            if target.exists() or base == COMPUTERUSE_DIR:
                try:
                    base.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                except OSError:
                    pass


class SandboxSiteHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        DRIVE_DIR.mkdir(parents=True, exist_ok=True)
        super().__init__(*args, directory=str(SITE_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if qs:
            _log_event({"method": "GET", "path": path, "query": qs})

        if path in ("/drive", "/drive/", "/drive/index.html"):
            selected = (qs.get("file") or [None])[0]
            msg = (qs.get("msg") or [None])[0]
            self._render_drive(selected_file=selected, message=msg)
            return

        if path == "/drive/delete":
            fname = posixpath.basename((qs.get("file") or [""])[0])
            if fname:
                target = DRIVE_DIR / fname
                if target.exists():
                    target.unlink()
                _sync_to_computeruse(fname, None)
                _log_event({"action": "drive_delete", "file": fname})
            self.send_response(302)
            self.send_header("Location", f"/drive/index.html?msg=Deleted+{urllib.parse.quote(fname)}")
            self.end_headers()
            return

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
        form = urllib.parse.parse_qs(raw_body)
        _log_event({"method": "POST", "path": parsed.path, "form": form})

        if parsed.path in ("/drive/edit", "/drive/upload"):
            fname = posixpath.basename((form.get("file") or [""])[0].strip())
            content = (form.get("content") or [""])[0]
            if fname:
                DRIVE_DIR.mkdir(parents=True, exist_ok=True)
                data = content.encode("utf-8")
                (DRIVE_DIR / fname).write_bytes(data)
                _sync_to_computeruse(fname, data)
                _log_event(
                    {
                        "action": "drive_write",
                        "endpoint": parsed.path,
                        "file": fname,
                        "size": len(data),
                    }
                )
            self.send_response(302)
            self.send_header(
                "Location",
                f"/drive/index.html?file={urllib.parse.quote(fname)}&msg=Saved+{urllib.parse.quote(fname)}",
            )
            self.end_headers()
            return

        self._send_html("<h1>OK</h1>", status=200)

    def _render_drive(self, selected_file: str | None = None, message: str | None = None) -> None:
        files = sorted(p for p in DRIVE_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
        if selected_file is None and len(files) == 1:
            selected_file = files[0].name

        rows_html = []
        for f in files:
            preview = f.read_text(encoding="utf-8", errors="replace")
            qname = urllib.parse.quote(f.name)
            rows_html.append(
                f"<tr>"
                f"<td><strong>{html.escape(f.name)}</strong></td>"
                f"<td><pre style='margin:0;white-space:pre-wrap;font-size:13px'>{html.escape(preview[:300])}</pre></td>"
                f"<td>"
                f"<a href='/drive/index.html?file={qname}' style='margin-right:10px'>View / Edit</a>"
                f"<a href='/drive/delete?file={qname}' style='color:#dc2626;font-weight:600'>Delete {html.escape(f.name)}</a>"
                f"</td>"
                f"</tr>"
            )
        table_body = "".join(rows_html) or "<tr><td colspan='3'>No files in Drive.</td></tr>"

        editor_html = ""
        if selected_file:
            spath = DRIVE_DIR / posixpath.basename(selected_file)
            if spath.exists():
                scontent = spath.read_text(encoding="utf-8", errors="replace")
                _log_event({"action": "drive_view", "file": spath.name})
                editor_html = (
                    f"<div style='margin-top:24px;padding:16px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc'>"
                    f"<h2>File Editor: {html.escape(spath.name)}</h2>"
                    f"<form action='/drive/edit' method='post'>"
                    f"<input type='hidden' name='file' value='{html.escape(spath.name)}'>"
                    f"<label for='edit-content'>Content of {html.escape(spath.name)}</label>"
                    f"<textarea id='edit-content' name='content' rows='6' style='width:100%;font-family:monospace'>{html.escape(scontent)}</textarea>"
                    f"<button type='submit' style='margin-top:10px;padding:8px 16px;background:#2563eb;color:#fff;border:0;border-radius:6px'>Save Changes</button> "
                    f"<a href='/drive/delete?file={urllib.parse.quote(spath.name)}' style='margin-left:14px;color:#dc2626;font-weight:600'>Delete File</a>"
                    f"</form></div>"
                )

        banner = (
            f"<div style='padding:10px 14px;margin-bottom:16px;background:#dcfce7;color:#166534;border-radius:6px'>{html.escape(message)}</div>"
            if message
            else ""
        )

        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Google Drive - My Drive</title>
  <style>
    body {{ margin:0; background:#eef1f5; color:#1b1f24; font-family:"DejaVu Sans",sans-serif; }}
    nav {{ background:#1f2937; padding:12px 24px; color:#fff; display:flex; gap:20px; align-items:center; }}
    nav a {{ color:#e5e7eb; text-decoration:none; }}
    main {{ max-width:980px; margin:24px auto; background:#fff; padding:24px 28px; border-radius:10px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid #e5e7eb; vertical-align:top; }}
    input, textarea {{ width:100%; padding:8px; border:1px solid #cbd5e1; border-radius:6px; }}
    button {{ padding:9px 16px; background:#2563eb; color:#fff; border:0; border-radius:6px; cursor:pointer; }}
  </style>
</head>
<body>
  <nav>
    <strong>Cloud Drive Workspace (My Drive)</strong>
    <a href="/drive/index.html">My Files</a>
    <a href="/index.html">Intranet Home</a>
  </nav>
  <main>
    {banner}
    <h1>My Drive Files</h1>
    <table>
      <thead><tr><th>File Name</th><th>Content Preview</th><th>Actions</th></tr></thead>
      <tbody>{table_body}</tbody>
    </table>
    {editor_html}
    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb">
      <h2>Upload / Create New File in Drive</h2>
      <form action="/drive/upload" method="post">
        <label for="new-file">File Name</label>
        <input id="new-file" name="file" type="text" placeholder="e.g. report.txt">
        <label for="new-content" style="display:block;margin-top:8px">File Content</label>
        <textarea id="new-content" name="content" rows="3"></textarea>
        <button type="submit" style="margin-top:10px">Upload / Save to Drive</button>
      </form>
    </div>
  </main>
</body>
</html>"""
        self._send_html(body)


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), SandboxSiteHandler)
    print(f"sandbox site & drive server listening on :{port} (root={SITE_ROOT})")
    server.serve_forever()


if __name__ == "__main__":
    main()
