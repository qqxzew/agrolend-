# One image for the gateway and the 8 internal geo services (entry point differs per compose service).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway/agroland ./gateway/agroland
COPY services/geo ./services/geo
COPY config ./config
COPY data ./data
COPY web ./web
RUN useradd -r -u 10001 app && mkdir -p /data && chown app /data
USER app
ENV PYTHONPATH=/srv/gateway AGROLAND_STATE_DIR=/data/gateway
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health').status==200 else 1)"
CMD ["uvicorn", "agroland.main:app", "--host", "0.0.0.0", "--port", "8080"]
