# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim

LABEL org.opencontainers.image.title="goodwe-prometheus-exporter" \
      org.opencontainers.image.description="Prometheus exporter for GoodWe solar inverters" \
      org.opencontainers.image.licenses="see LICENSE"

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin exporter

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LISTEN_PORT=9877

USER 10001
EXPOSE 9877

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('LISTEN_PORT','9877'), timeout=3)"]

ENTRYPOINT ["python", "-m", "goodwe_exporter"]
