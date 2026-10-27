#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

if ! xdpyinfo >/dev/null 2>&1; then
  rm -f /tmp/.X99-lock
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
  for _ in $(seq 1 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
  xdpyinfo >/dev/null 2>&1 || { echo "Xvfb failed to start" >&2; cat /tmp/xvfb.log >&2; exit 1; }
fi

xsetroot -solid '#2e3440' || true
openbox >/tmp/openbox.log 2>&1 &
sleep 0.4
tint2 >/tmp/tint2.log 2>&1 &

if [ -d /srv/vpi_web ]; then
  python3 -m http.server 8081 --directory /srv/vpi_web >/tmp/vpi_web.log 2>&1 &
fi

x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -quiet >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &

exec /opt/venv/bin/uvicorn actuator:app --host 0.0.0.0 --port 8000 --app-dir /opt
