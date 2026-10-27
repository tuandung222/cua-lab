"""Concrete EnvSetupInstruction implementations for VPI-Bench and general benchmarks."""

from __future__ import annotations

import base64
import binascii
import posixpath
import shlex
from typing import Any

from ..protocols import SandboxEnvProtocol
from ..types import Action
from .base import EnvSetupInstruction


def _decode_content(raw_content: str | None, raw_b64: str | None) -> bytes:
    """Decode content from either plaintext `content` or `b64_data`.

    Note: In VPI-Bench's raw JSON files on Hugging Face, the `b64_data` field
    is stored as plaintext UTF-8 (which their loader base64-encodes before sending).
    We handle both valid base64 strings and raw UTF-8 strings transparently.
    """
    if raw_content is not None:
        return raw_content.encode("utf-8")
    if not raw_b64:
        return b""
    # Check if raw_b64 is strictly valid base64 that decodes to printable UTF-8 without newlines/spaces
    if "\n" not in raw_b64 and " " not in raw_b64 and len(raw_b64) % 4 == 0:
        try:
            decoded = base64.b64decode(raw_b64, validate=True)
            decoded.decode("utf-8")
            return decoded
        except (binascii.Error, UnicodeDecodeError):
            pass
    return raw_b64.encode("utf-8")


class FileCreateInstruction(EnvSetupInstruction):
    """Creates a file inside the sandbox and mirrors it to the local Drive store."""

    def __init__(self, path: str, content_bytes: bytes):
        self.path = path
        self.content_bytes = content_bytes

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        b64 = base64.b64encode(self.content_bytes).decode("ascii")
        parent = posixpath.dirname(self.path) or "/"
        basename = posixpath.basename(self.path)
        drive_dir = "/srv/site/drive_files"
        drive_path = posixpath.join(drive_dir, basename)
        extra_cp = ""
        if self.path.startswith("/home/computeruse/"):
            rel = self.path[len("/home/computeruse/") :]
            root_mirror = posixpath.join("/root", rel)
            root_parent = posixpath.dirname(root_mirror) or "/root"
            extra_cp = f" && mkdir -p {shlex.quote(root_parent)} && cp {shlex.quote(self.path)} {shlex.quote(root_mirror)}"
        cmd = (
            f"mkdir -p {shlex.quote(parent)} {shlex.quote(drive_dir)} && "
            f"printf '%s' {shlex.quote(b64)} | base64 -d > {shlex.quote(self.path)} && "
            f"cp {shlex.quote(self.path)} {shlex.quote(drive_path)}"
            f"{extra_cp}"
        )
        return env.exec_shell(cmd)

    def cleanup(self, env: SandboxEnvProtocol) -> None:
        basename = posixpath.basename(self.path)
        drive_path = posixpath.join("/srv/site/drive_files", basename)
        extra_rm = ""
        if self.path.startswith("/home/computeruse/"):
            rel = self.path[len("/home/computeruse/") :]
            extra_rm = " " + shlex.quote(posixpath.join("/root", rel))
        env.exec_shell(f"rm -f {shlex.quote(self.path)} {shlex.quote(drive_path)}{extra_rm}")


class PathDeleteInstruction(EnvSetupInstruction):
    """Deletes a file or directory inside the sandbox."""

    def __init__(self, path: str):
        self.path = path

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        return env.exec_shell(f"rm -rf {shlex.quote(self.path)}")


class BrowserLaunchInstruction(EnvSetupInstruction):
    """Opens a target URL in the active environment (Desktop Chromium or Browser CDP)."""

    def __init__(self, url: str):
        self.url = url

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        if env.name == "browser":
            return env.act(Action(type="goto", url=self.url))
        py_code = (
            "import os, shutil, subprocess, time\n"
            "ud = '/tmp/chromium-' + 'desktop'\n"
            "os.makedirs('/home/computeruse/Downloads', exist_ok=True)\n"
            "if os.path.islink('/root/Downloads') or os.path.isfile('/root/Downloads'): os.unlink('/root/Downloads')\n"
            "elif os.path.isdir('/root/Downloads'): shutil.rmtree('/root/Downloads', ignore_errors=True)\n"
            "os.symlink('/home/computeruse/Downloads', '/root/Downloads')\n"
            "subprocess.run(['pkill', '-9', '-f', '[c]hromium-desktop'], check=False)\n"
            "subprocess.run(['pkill', '-9', '-x', 'xterm'], check=False)\n"
            "shutil.rmtree(ud, ignore_errors=True)\n"
            "f = open('/tmp/desktop_browser.log', 'w')\n"
            "subprocess.Popen([\n"
            "  'chromium', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',\n"
            "  f'--user-data-dir={ud}', '--no-first-run',\n"
            "  '--no-default-browser-check', '--disable-session-crashed-bubble',\n"
            "  '--disable-features=Translate,MediaRouter,OptimizationHints',\n"
            "  '--window-position=0,0', '--window-size=1280,752',\n"
            f"  {self.url!r}\n"
            "], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)\n"
            "time.sleep(2.5)\n"
            "print('launched')\n"
        )
        return env.exec_shell(f"python3 -c {shlex.quote(py_code)}")


class LibreOfficeOpenInstruction(EnvSetupInstruction):
    """Opens a spreadsheet or CSV/text file on the Desktop."""

    def __init__(self, path: str):
        self.path = path

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        py_code = (
            "import shutil, subprocess, time\n"
            f"p = {self.path!r}\n"
            "cmd = ['libreoffice', '--norestore', '--calc', p] if shutil.which('libreoffice') else ['mousepad', p]\n"
            "subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)\n"
            "time.sleep(1.0)\n"
        )
        return env.exec_shell(f"python3 -c {shlex.quote(py_code)}")


class RunCommandInstruction(EnvSetupInstruction):
    """Executes an arbitrary shell command in the background during environment setup."""

    def __init__(self, command: str):
        self.command = command

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        py_code = (
            "import subprocess\n"
            "f = open('/tmp/setup_cmd.log', 'w')\n"
            f"subprocess.Popen(['bash', '-c', {self.command!r}], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)\n"
        )
        return env.exec_shell(f"python3 -c {shlex.quote(py_code)}")


class CloseAllInstruction(EnvSetupInstruction):
    """Closes open user windows and cleans temporary directories."""

    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        env.reset()
        return env.exec_shell(
            'pkill -9 -f "[c]hromium-desktop" || true; '
            'rm -rf /home/computeruse/Downloads/* /tmp/vpi_web_requests.jsonl 2>/dev/null || true'
        )


class SetupInstructionFactory:
    """Factory converting raw benchmark environment instruction dicts into Command objects."""

    @staticmethod
    def from_dict(raw: dict[str, Any], url_rewriter=None) -> EnvSetupInstruction:
        kind = (raw.get("instruction_type") or "").upper()
        if kind == "FILE_CREATE":
            path = raw["path"]
            content = _decode_content(raw.get("content"), raw.get("b64_data"))
            return FileCreateInstruction(path=path, content_bytes=content)
        if kind == "PATH_DELETE":
            return PathDeleteInstruction(path=raw["path"])
        if kind == "FIREFOX_OPEN":
            url = raw["url"]
            if url_rewriter is not None:
                url = url_rewriter(url)
            return BrowserLaunchInstruction(url=url)
        if kind == "LIBREOFFICE_CALC_OPEN":
            return LibreOfficeOpenInstruction(path=raw["path"])
        if kind == "RUN_COMMAND":
            cmd_bytes = _decode_content(raw.get("content"), raw.get("b64_data"))
            return RunCommandInstruction(command=cmd_bytes.decode("utf-8", errors="replace"))
        if kind == "CLOSE_ALL":
            return CloseAllInstruction()
        raise ValueError(f"Unsupported setup instruction_type: {kind!r}")
