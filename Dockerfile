FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PASSAT_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8080 \
    COOKIE_SECURE=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && groupadd --gid 10001 passat \
    && useradd --uid 10001 --gid passat --no-create-home --shell /usr/sbin/nologin passat \
    && mkdir /data \
    && chown passat:passat /data

COPY passat_charge/ ./passat_charge/
RUN chmod -R a+rX /app/passat_charge
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).close()"]

CMD ["python", "-m", "passat_charge"]
