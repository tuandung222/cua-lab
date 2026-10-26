#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

Xvfb :99 -screen 0 1280x800x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
for _ in $(seq 1 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done

openbox >/tmp/openbox.log 2>&1 &
sleep 0.3

python3 -m http.server 8000 --directory /srv/site >/tmp/site.log 2>&1 &

chromium \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --user-data-dir=/tmp/chromium \
  --remote-debugging-port=9222 \
  "--remote-allow-origins=*" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=Translate,MediaRouter,OptimizationHints \
  --window-position=0,0 \
  --window-size=1280,800 \
  --start-maximized \
  http://127.0.0.1:8000/ >/tmp/chromium.log 2>&1 &

x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -quiet >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &

for _ in $(seq 1 80); do
  curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1 && break
  sleep 0.25
done

exec /opt/venv/bin/uvicorn actuator:app --host 0.0.0.0 --port 8000 --app-dir /opt
