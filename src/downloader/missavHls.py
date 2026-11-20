"""Fetch HLS media in parallel and remux it to MP4."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Lock
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
from loguru import logger


_URI = re.compile(r'URI="([^"]+)"')
_IMAGE_HEADERS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8")
_SEGMENT_WORKERS = 4


def _fetch(url, headers, impersonate, proxies, timeout, session=None,
           *, stage="resource", return_response=False):
    client = session or requests
    for attempt in range(3):
        try:
            response = client.get(
                url, headers=headers, impersonate=impersonate,
                proxies=proxies, timeout=timeout,
            )
            if response.status_code in (401, 403):
                host = urlparse(url).hostname
                raise RuntimeError(f"HLS {stage} denied (HTTP {response.status_code}, {host})")
            response.raise_for_status()
            return response if return_response else response.content
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

    response = _fetch(playlist_url, headers, impersonate, proxies, timeout,
                      stage="media playlist", return_response=True)
    playlist_url = response.url
    playlist = response.content.decode("utf-8-sig")
    lines = playlist.splitlines()
    if not lines or lines[0].strip() != "#EXTM3U" or "#EXT-X-STREAM-INF" in playlist:
        raise ValueError("Expected a media playlist")
    if "#EXT-X-BYTERANGE" in playlist:
        raise ValueError("HLS byte ranges are not supported")

    video_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".missav-hls-", dir=video_path.parent) as temp_dir:
        temp = Path(temp_dir)
        segments = []
        local_lines = []
        resources = {}
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("#EXT-X-KEY:", "#EXT-X-MAP:")):
                match = _URI.search(line)
                if match:
                    resource_url = urljoin(playlist_url, match.group(1))
                    if resource_url not in resources:
                        name = f"resource-{len(resources):04d}.bin"
                        data = _fetch(resource_url, headers, impersonate, proxies, timeout,
                                      stage="key or initialization map")
                        (temp / name).write_bytes(data)
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

        total = len(segments)
        workers = min(_SEGMENT_WORKERS, total)
        completed = 0
        progress_lock = Lock()
        failed = Event()

        def fetch_group(items):
            nonlocal completed
            try:
                # Keep each curl session on its own worker.
                with requests.Session() as session:
                    for number, (url, path) in items:
                        if failed.is_set():
                            return
                        data = _fetch(url, headers, impersonate, proxies, timeout, session,
                                      stage=f"segment {number}/{total}")
                        if path.suffix == ".ts":
                            data = _fix_ts(data)
                        path.write_bytes(data)
                        with progress_lock:
                            completed += 1
                            if completed % 80 == 0 or completed == total:
                                logger.info(f"HLS segments: {completed}/{total}")
            except Exception:
                failed.set()
                raise

        numbered = list(enumerate(segments, start=1))
        logger.info(f"Downloading {total} HLS segments with {workers} workers")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for _ in executor.map(fetch_group, (numbered[index::workers] for index in range(workers))):
                pass

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
