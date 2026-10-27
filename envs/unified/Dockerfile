FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb x11vnc novnc websockify openbox tint2 \
      xterm mousepad pcmanfm xdotool scrot x11-utils xclip \
      python3 python3-venv \
      fonts-dejavu-core fonts-noto-color-emoji \
      ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn pillow playwright

COPY desktop/actuator.py /opt/desktop_actuator.py
COPY browser/actuator.py /opt/browser_actuator.py
COPY desktop/tint2rc /root/.config/tint2/tint2rc
COPY desktop/menu.xml /root/.config/openbox/menu.xml
COPY desktop/desktops/ /root/.local/share/applications/
COPY desktop/seed/ /opt/seed/
COPY browser/site/gen.py /opt/gen_site.py
COPY unified/start.sh /opt/start.sh

RUN chmod +x /opt/start.sh \
    && mkdir -p /root/Desktop /root/data /root/archive \
    && cp /opt/seed/notes.txt /root/notes.txt \
    && cp /opt/seed/data/* /root/data/ \
    && python3 /opt/gen_site.py

EXPOSE 8001 8002 6080 6081 9222

CMD ["/opt/start.sh"]
