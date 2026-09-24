FROM node:24-alpine

RUN apk add --no-cache \
    bash \
    curl \
    docker-cli \
    docker-cli-buildx \
    docker-cli-compose \
    git \
    iproute2
