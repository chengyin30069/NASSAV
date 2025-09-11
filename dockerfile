FROM archlinux:base

RUN pacman -Syu --noconfirm git ffmpeg python && \
    rm -rf /var/cache/pacman/pkg/*

WORKDIR /NASSAV

COPY . .

RUN python -m venv .

RUN ./bin/pip install -r requirements.txt

ENTRYPOINT ["./bin/python", "main.py"]