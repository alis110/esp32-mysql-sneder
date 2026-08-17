FROM python:3.12-alpine

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    PORT=80 \
    HOST=0.0.0.0 \
    API_TOKEN=lab-token

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py replica.py dashboard.html /app/

EXPOSE 80
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:80/api/health')"

CMD ["python", "-u", "/app/app.py"]
