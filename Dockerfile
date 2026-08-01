# --- stage 1: build the dashboard -------------------------------------------
FROM node:20-alpine AS web

WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY intentdesk/ ./intentdesk/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY --from=web /build/dist ./web/dist

# Run unprivileged — this container is internet-facing behind Traefik.
RUN useradd --system --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "intentdesk.api.app:app", "--host", "0.0.0.0", "--port", "8100"]
