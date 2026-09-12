FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

WORKDIR /app
RUN addgroup -S web && adduser -S -G web web
COPY --chown=web:web web/server.py web/index.html ./
USER web

EXPOSE 8080
CMD ["python", "server.py"]
