FROM node:22-alpine AS ui

WORKDIR /src/web/client
COPY web/client/package.json web/client/package-lock.json ./
RUN npm ci
COPY web/client/index.html web/client/tsconfig.json web/client/vite.config.ts ./
COPY web/client/src ./src
RUN npm run build && test -s dist/index.html

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRADINGAGENTS_WEB_DATA_DIR=/var/lib/tradingagents-web \
    XDG_CACHE_HOME=/var/lib/tradingagents-web/cache

WORKDIR /app
COPY pyproject.toml README.md ./
COPY tradingagents ./tradingagents
COPY cli ./cli
COPY web/*.py ./web/
RUN pip install --no-cache-dir .
COPY --from=ui /src/web/client/dist ./web/client/dist
RUN test -s web/client/dist/index.html && \
    groupadd --gid 10001 web && \
    useradd --uid 10001 --gid web --no-create-home --home-dir /var/lib/tradingagents-web web && \
    mkdir -p /var/lib/tradingagents-web && \
    chown 10001:10001 /var/lib/tradingagents-web && \
    chmod 700 /var/lib/tradingagents-web
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
