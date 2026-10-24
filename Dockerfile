FROM python:3-slim
LABEL org.opencontainers.image.source="https://github.com/111blackeagle111/pylontech-console-monitor" \
      org.opencontainers.image.description="Web dashboard for Pylontech battery banks via the RS232 console port" \
      org.opencontainers.image.licenses="MIT"
RUN pip install --no-cache-dir pyserial==3.5 \
 && useradd -u 1000 -m app \
 && mkdir /data && chown app /data
COPY pylon_monitor.py /app/pylon_monitor.py
USER app
CMD ["python3", "-u", "/app/pylon_monitor.py"]
