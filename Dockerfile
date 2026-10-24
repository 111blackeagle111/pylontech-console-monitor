FROM python:3-slim
RUN pip install --no-cache-dir pyserial==3.5 \
 && useradd -u 1000 -m app \
 && mkdir /data && chown app /data
COPY pylon_monitor.py /app/pylon_monitor.py
USER app
CMD ["python3", "-u", "/app/pylon_monitor.py"]
