FROM golang:1.22-alpine AS m3u8-builder

WORKDIR /build

RUN apk add --no-cache git

RUN git clone --depth 1 --branch v1.5.2 https://github.com/Greyh4t/m3u8-Downloader-Go.git src && \
    cd src && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /build/m3u8-Downloader-Go

FROM alpine:3.23 AS flaresolverr-source

RUN apk add --no-cache git && \
    git clone --depth 1 --branch v3.5.2 \
      https://github.com/FlareSolverr/FlareSolverr.git /flaresolverr

FROM alpine:3.23 AS nassav

WORKDIR /NASSAV

RUN apk add --no-cache \
      chromium chromium-chromedriver dumb-init ffmpeg python3 \
      xauth xvfb && \
    addgroup -S flaresolverr && \
    adduser -S -G flaresolverr -h /app flaresolverr && \
    mkdir -p /app && \
    mv /usr/lib/chromium/chromedriver /app/chromedriver && \
    ln -s /app/chromedriver /usr/lib/chromium/chromedriver && \
    chown flaresolverr:flaresolverr /app /app/chromedriver && \
    python3 -m venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH

COPY --from=flaresolverr-source /flaresolverr/requirements.txt /app/requirements.txt
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev && \
    pip install --no-cache-dir --no-compile \
      -r /app/requirements.txt -r /NASSAV/requirements.txt && \
    apk del .build-deps

COPY --from=flaresolverr-source /flaresolverr/src/ /app/
COPY --from=flaresolverr-source /flaresolverr/package.json /package.json
COPY --chown=flaresolverr:flaresolverr . .
COPY --from=m3u8-builder --chown=flaresolverr:flaresolverr /build/m3u8-Downloader-Go tools/m3u8-Downloader-Go
RUN mkdir -p /app/.config/chromium/Crash\ Reports/pending /NASSAV/db /NASSAV/logs && \
    chown -R flaresolverr:flaresolverr /app/.config /NASSAV

USER flaresolverr
ENV HOST=127.0.0.1

ENTRYPOINT ["/usr/bin/dumb-init", "--", "python", "-u", "/NASSAV/docker_entrypoint.py"]
