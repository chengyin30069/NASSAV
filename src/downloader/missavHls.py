"""Fetch MissAV HLS media with the same browser profile used for its pages."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
from loguru import logger


_URI = re.compile(r'URI="([^"]+)"')
_IMAGE_HEADERS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8")


def _fetch(url, headers, impersonate, proxies, timeout, session=None):
    client = session or requests
    for attempt in range(3):
        try:
            response = client.get(
                url, headers=headers, impersonate=impersonate,
                proxies=proxies, timeout=timeout,
            )
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise


def _fix_ts(data):
    """Remove an image prefix when the segment contains hidden MPEG-TS packets."""
    if not data.startswith(_IMAGE_HEADERS):
        return data
    for offset in range(len(data) - 188):
        if data[offset] != 0x47 or data[offset + 188] != 0x47:
            continue
        if len(data) > offset + 376 and data[offset + 376] != 0x47:
            continue
        pid = ((data[offset + 1] & 0x1f) << 8) | data[offset + 2]
        if pid in (0, 17):
            return data[offset:]
    raise ValueError("Cannot locate MPEG-TS data after image prefix")


def download_media(playlist_url, video_path, headers, impersonate, proxies=None, timeout=30):
    """Download an HLS media playlist and remux it to MP4."""
    video_path = Path(video_path)
    if video_path.exists():
        raise FileExistsError(f"Video already exists: {video_path}")

    playlist = _fetch(playlist_url, headers, impersonate, proxies, timeout).decode("utf-8-sig")
    if "#EXTM3U" not in playlist or "#EXT-X-STREAM-INF" in playlist:
        raise ValueError("Expected a media playlist")
    if "#EXT-X-BYTERANGE" in playlist:
        raise ValueError("HLS byte ranges are not supported")

    video_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".missav-hls-", dir=video_path.parent) as temp_dir:
        temp = Path(temp_dir)
        segments = []
        local_lines = []
        resources = {}
        for line in playlist.splitlines():
            stripped = line.strip()
            if stripped.startswith(("#EXT-X-KEY:", "#EXT-X-MAP:")):
                match = _URI.search(line)
                if match:
                    resource_url = urljoin(playlist_url, match.group(1))
                    if resource_url not in resources:
                        name = f"resource-{len(resources):04d}.bin"
                        (temp / name).write_bytes(_fetch(resource_url, headers, impersonate, proxies, timeout))
                        resources[resource_url] = name
                    line = line[:match.start(1)] + resources[resource_url] + line[match.end(1):]
            elif stripped and not stripped.startswith("#"):
                segment_url = urljoin(playlist_url, stripped)
                suffix = Path(urlparse(segment_url).path).suffix.lower()
                if suffix not in (".ts", ".m4s", ".mp4"):
                    suffix = ".ts"
                name = f"segment-{len(segments):06d}{suffix}"
                segments.append((segment_url, temp / name))
                line = name
            local_lines.append(line)
        if not segments:
            raise ValueError("Media playlist contains no segments")

        (temp / "local.m3u8").write_text("\n".join(local_lines) + "\n", encoding="utf-8")

        progress = 0
        progress_lock = Lock()

        def fetch_group(items):
            nonlocal progress
            # A curl handle belongs to one worker and is reused for that worker's requests.
            with requests.Session() as session:
                for url, path in items:
                    data = _fetch(url, headers, impersonate, proxies, timeout, session)
                    if path.suffix == ".ts":
                        data = _fix_ts(data)
                    path.write_bytes(data)
                    with progress_lock:
                        progress += 1
                        if progress % 80 == 0 or progress == len(segments):
                            logger.info(f"MissAV segments: {progress}/{len(segments)}")

        logger.info(f"Downloading {len(segments)} MissAV segments")
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(fetch_group, (segments[index::4] for index in range(4))))

        temporary_video = temp / "video.mp4"
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-protocol_whitelist", "file,crypto,data", "-allowed_extensions", "ALL",
             "-i", str(temp / "local.m3u8"), "-c", "copy", str(temporary_video)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not temporary_video.is_file():
            raise RuntimeError(f"FFmpeg remux failed: {result.stderr.strip()}")
        if video_path.exists():
            raise FileExistsError(f"Video already exists: {video_path}")
        temporary_video.replace(video_path)
