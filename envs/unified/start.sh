#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

# 1. Start Desktop Sandbox on DISPLAY=:99 (Actuator :8001, noVNC :6080)
if ! DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
  rm -f /tmp/.X99-lock
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp -ac >/tmp/xvfb99.log 2>&1 &
  for _ in $(seq 1 50); do DISPLAY=:99 xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
  DISPLAY=:99 xdpyinfo >/dev/null 2>&1 || { echo "Xvfb :99 failed" >&2; cat /tmp/xvfb99.log >&2; exit 1; }
fi

DISPLAY=:99 xsetroot -solid '#2e3440' || true
DISPLAY=:99 openbox >/tmp/openbox99.log 2>&1 &
sleep 0.4
DISPLAY=:99 tint2 >/tmp/tint2.log 2>&1 &
x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -quiet >/tmp/x11vnc99.log 2>&1 &
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify6080.log 2>&1 &
DISPLAY=:99 /opt/venv/bin/uvicorn desktop_actuator:app --host 0.0.0.0 --port 8001 --app-dir /opt >/tmp/desktop_actuator.log 2>&1 &

# 2. Start Browser Sandbox on DISPLAY=:98 (Actuator :8002, noVNC :6081)
if ! DISPLAY=:98 xdpyinfo >/dev/null 2>&1; then
  rm -f /tmp/.X98-lock
  Xvfb :98 -screen 0 1280x800x24 -nolisten tcp -ac >/tmp/xvfb98.log 2>&1 &
  for _ in $(seq 1 50); do DISPLAY=:98 xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
  DISPLAY=:98 xdpyinfo >/dev/null 2>&1 || { echo "Xvfb :98 failed" >&2; cat /tmp/xvfb98.log >&2; exit 1; }
fi

DISPLAY=:98 openbox >/tmp/openbox98.log 2>&1 &
sleep 0.3
python3 /opt/site_server.py >/tmp/site.log 2>&1 &
if [ -d /srv/vpi_web ]; then
  python3 -m http.server 8081 --directory /srv/vpi_web >/tmp/vpi_web.log 2>&1 &
fi

rm -f /tmp/chromium/Singleton*
DISPLAY=:98 chromium \
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
  http://127.0.0.1:8080/ >/tmp/chromium.log 2>&1 &

x11vnc -display :98 -nopw -forever -shared -rfbport 5901 -quiet >/tmp/x11vnc98.log 2>&1 &
websockify --web=/usr/share/novnc 6081 127.0.0.1:5901 >/tmp/websockify6081.log 2>&1 &

for _ in $(seq 1 80); do
  curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1 || {
  echo "chromium CDP did not come up" >&2; tail -20 /tmp/chromium.log >&2; exit 1;
}

exec env DISPLAY=:98 /opt/venv/bin/uvicorn browser_actuator:app --host 0.0.0.0 --port 8002 --app-dir /opt
