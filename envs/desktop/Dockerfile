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
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn pillow

COPY actuator.py /opt/actuator.py
COPY start.sh /opt/start.sh
COPY tint2rc /root/.config/tint2/tint2rc
COPY menu.xml /root/.config/openbox/menu.xml
COPY desktops/ /root/.local/share/applications/
COPY seed/ /opt/seed/

RUN chmod +x /opt/start.sh \
    && mkdir -p /root/Desktop /root/data /root/archive /home/computeruse/files /home/computeruse/Downloads /srv/site/drive_files /srv/vpi_web \
    && cp /opt/seed/notes.txt /root/notes.txt \
    && cp /opt/seed/data/* /root/data/

EXPOSE 8000 5900 6080

CMD ["/opt/start.sh"]
