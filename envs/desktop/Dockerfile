FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc novnc websockify openbox tint2 \
      xterm mousepad pcmanfm xdotool scrot x11-utils xclip \
      python3 python3-venv \
      fonts-dejavu-core ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn pillow

COPY actuator.py /opt/actuator.py
COPY start.sh /opt/start.sh
COPY tint2rc /root/.config/tint2/tint2rc
COPY menu.xml /root/.config/openbox/menu.xml
COPY desktops/ /root/.local/share/applications/
COPY seed/ /tmp/seed/

RUN chmod +x /opt/start.sh \
    && mkdir -p /root/Desktop /root/data /root/archive \
    && cp /tmp/seed/notes.txt /root/notes.txt \
    && cp /tmp/seed/data/* /root/data/ \
    && rm -rf /tmp/seed

EXPOSE 8000 5900 6080

CMD ["/opt/start.sh"]
