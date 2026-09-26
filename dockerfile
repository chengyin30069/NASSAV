FROM golang:1.22-alpine AS m3u8-builder

WORKDIR /build

RUN apk add --no-cache git

RUN git clone https://github.com/Greyh4t/m3u8-Downloader-Go.git src && \
    cd src && git checkout tags/v1.5.2 && \
    CGO_ENABLED=0 go build -o /build/m3u8-Downloader-Go

FROM python:3.11-slim AS nassav

WORKDIR /NASSAV

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY . .

COPY --from=m3u8-builder /build/m3u8-Downloader-Go tools/m3u8-Downloader-Go

RUN python -m venv . && ./bin/pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["./bin/python", "main.py"]
