FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb x11vnc novnc websockify openbox \
      xdotool scrot x11-utils \
      python3 python3-venv \
      fonts-dejavu-core fonts-noto-color-emoji \
      ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn pillow playwright

COPY actuator.py /opt/actuator.py
COPY start.sh /opt/start.sh
COPY site/gen.py /opt/gen_site.py
COPY site/server.py /opt/site_server.py

RUN chmod +x /opt/start.sh \
    && mkdir -p /home/computeruse/files /home/computeruse/Downloads /srv/site/drive_files /srv/vpi_web \
    && python3 /opt/gen_site.py

EXPOSE 8000 5900 6080 9222

CMD ["/opt/start.sh"]
