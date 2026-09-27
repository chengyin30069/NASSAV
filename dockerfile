FROM golang:1.22-alpine AS m3u8-builder

WORKDIR /build

RUN apk add --no-cache git

RUN git clone --depth 1 --branch v1.5.2 https://github.com/Greyh4t/m3u8-Downloader-Go.git src && \
    cd src && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /build/m3u8-Downloader-Go

FROM ghcr.io/flaresolverr/flaresolverr:v3.5.2 AS nassav

USER root

WORKDIR /NASSAV

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY --chown=flaresolverr:flaresolverr . .
COPY --from=m3u8-builder --chown=flaresolverr:flaresolverr /build/m3u8-Downloader-Go tools/m3u8-Downloader-Go
RUN mkdir -p /NASSAV/db /NASSAV/logs && \
    chown -R flaresolverr:flaresolverr /NASSAV

USER flaresolverr
ENV HOST=127.0.0.1

ENTRYPOINT ["/usr/bin/dumb-init", "--", "python", "-u", "/NASSAV/docker_entrypoint.py"]
