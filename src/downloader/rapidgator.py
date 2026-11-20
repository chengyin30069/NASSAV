"""Resolve a MissAV Rapidgator link and stream the resulting video file."""

from contextlib import closing
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
from loguru import logger


VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts"}
_FILE_ID = re.compile(r"^[a-zA-Z0-9]{8,64}$")


def _file_id(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
        "rapidgator.net", "www.rapidgator.net", "rg.to", "www.rg.to"
    }:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "file" or not _FILE_ID.fullmatch(parts[1]):
        return None
    return parts[1]


class _RapidgatorLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        url = urljoin("https://missav.ai/", href)
        if _file_id(url):
            self.links.append(url)


def extract_rapidgator_link(html):
    parser = _RapidgatorLinks()
    parser.feed(html)
    return parser.links[0] if parser.links else None


def configured_backend():
    backend = os.getenv("RAPIDGATOR_BACKEND", "").lower()
    native = bool(os.getenv("RAPIDGATOR_LOGIN") and os.getenv("RAPIDGATOR_PASSWORD"))
    portal = bool(os.getenv("STORAGE_PORTAL_API_KEY"))
    manual = bool(os.getenv("RAPIDGATOR_DIRECT_URL") and os.getenv("RAPIDGATOR_DIRECT_FILENAME")
                  and os.getenv("RAPIDGATOR_DIRECT_FILE_ID"))
    if backend == "manual":
        return "manual" if manual else None
    if backend == "rapidgator":
        return "rapidgator" if native else None
    if backend == "storage_portal":
        return "storage_portal" if portal else None
    return "manual" if manual else "rapidgator" if native else "storage_portal" if portal else None


def _api_response(response, service):
    try:
        response.raise_for_status()
        body = response.json()
    except (ValueError, requests.exceptions.RequestException) as exc:
        raise RuntimeError(f"{service} API request failed (HTTP {response.status_code})") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"{service} API returned an invalid response")
    payload = body.get("response") if service == "Rapidgator" else body.get("data")
    if not isinstance(payload, dict) or (service == "Storage Portal" and not body.get("success")):
        raise RuntimeError(f"{service} API rejected the request (status {body.get('status', 'unknown')})")
    return payload


def _resolve_native(public_url, timeout, proxies, impersonate):
    file_id = _file_id(public_url)
    try:
        with requests.Session() as session:
            common = {"timeout": timeout, "proxies": proxies, "impersonate": impersonate}
            login = session.get(
                "https://rapidgator.net/api/v2/user/login",
                params={"login": os.environ["RAPIDGATOR_LOGIN"], "password": os.environ["RAPIDGATOR_PASSWORD"]},
                **common,
            )
            token = _api_response(login, "Rapidgator").get("token")
            if not token:
                raise RuntimeError("Rapidgator login did not return a token")
            params = {"token": token, "file_id": file_id}
            info = _api_response(session.get("https://rapidgator.net/api/v2/file/info", params=params, **common), "Rapidgator")
            file_info = info.get("file") or {}
            result = _api_response(session.get("https://rapidgator.net/api/v2/file/download", params=params, **common), "Rapidgator")
            return result.get("download_url"), file_info.get("name"), file_info.get("size")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("Rapidgator API network request failed") from exc


def _resolve_portal(public_url, timeout, proxies, impersonate):
    base = "https://www.storage-portal.com/api/external/v1"
    headers = {"X-Api-Key": os.environ["STORAGE_PORTAL_API_KEY"]}
    try:
        with requests.Session() as session:
            common = {"headers": headers, "timeout": timeout, "proxies": proxies, "impersonate": impersonate}
            result = _api_response(session.post(base + "/unrestrict", json={"url": public_url}, **common), "Storage Portal")
            deadline = time.monotonic() + 3600
            while not result.get("download_ready"):
                link_id = result.get("linkId")
                if not isinstance(link_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", link_id):
                    raise RuntimeError("Storage Portal did not return a valid link ID")
                if result.get("remote_status") == "error" or time.monotonic() >= deadline:
                    raise RuntimeError("Storage Portal could not prepare the file")
                time.sleep(min(max(float(result.get("poll_after_seconds") or 2), 1), 60))
                result = _api_response(session.get(base + "/link/" + link_id, **common), "Storage Portal")
            return result.get("link"), result.get("filename"), result.get("filesize")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("Storage Portal API network request failed") from exc


def _safe_filename(filename):
    if not isinstance(filename, str):
        raise ValueError("Direct download did not provide a filename")
    filename = filename.replace("\\", "/").split("/")[-1]
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"Rapidgator file is not a supported video: {suffix or 'unknown extension'}")
    return suffix


def download_rapidgator(public_url, folder, avid, proxies=None, impersonate="chrome120", timeout=30):
    """Use the configured authorized API, then save a video with Range resume."""
    if not _file_id(public_url):
        raise ValueError("Invalid Rapidgator file URL")
    backend = configured_backend()
    if not backend:
        raise ValueError("Set Rapidgator credentials, Storage Portal API key, or a manual direct URL")
    logger.info(f"Resolving Rapidgator file using {backend}")
    if backend == "manual":
        if os.environ["RAPIDGATOR_DIRECT_FILE_ID"] != _file_id(public_url):
            raise ValueError("Manual Rapidgator URL is for a different file ID")
        direct_url = os.environ["RAPIDGATOR_DIRECT_URL"]
        filename = os.environ["RAPIDGATOR_DIRECT_FILENAME"]
        expected_size = None
    elif backend == "rapidgator":
        direct_url, filename, expected_size = _resolve_native(public_url, timeout, proxies, impersonate)
    else:
        direct_url, filename, expected_size = _resolve_portal(public_url, timeout, proxies, impersonate)
    if not isinstance(direct_url, str) or urlparse(direct_url).scheme != "https":
        raise ValueError("Provider did not return an HTTPS download link")
    suffix = _safe_filename(filename)
    expected_size = int(expected_size) if expected_size is not None else None
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{avid}{suffix}"
    partial = folder / f".{avid}.{_file_id(public_url)}{suffix}.part"
    if target.exists():
        return target
    offset = partial.stat().st_size if partial.exists() else 0
    if expected_size is not None and offset > expected_size:
        raise ValueError("Partial Rapidgator file is larger than the source")
    if expected_size and offset == expected_size:
        partial.replace(target)
        return target
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    if backend == "manual":
        if os.getenv("RAPIDGATOR_DIRECT_COOKIE"):
            headers["Cookie"] = os.environ["RAPIDGATOR_DIRECT_COOKIE"]
        if os.getenv("RAPIDGATOR_DIRECT_USER_AGENT"):
            headers["User-Agent"] = os.environ["RAPIDGATOR_DIRECT_USER_AGENT"]
    try:
        with requests.Session() as session:
            with closing(session.get(
                direct_url, headers=headers, stream=True, timeout=timeout,
                proxies=proxies, impersonate=impersonate,
            )) as response:
                if offset and response.status_code == 416:
                    total = response.headers.get("Content-Range", "")
                    if total == f"bytes */{offset}":
                        partial.replace(target)
                        return target
                if response.status_code not in (200, 206):
                    raise RuntimeError(f"Rapidgator file request failed (HTTP {response.status_code})")
                if response.headers.get("Content-Type", "").lower().startswith(("text/", "application/json")):
                    raise RuntimeError("Rapidgator returned a web page instead of a video file")
                if offset and response.status_code == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-"):
                        raise RuntimeError("Rapidgator returned a different byte range")
                else:
                    offset = 0
                declared_length = response.headers.get("Content-Length")
                transferred = 0
                with partial.open("ab" if offset else "wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
                            transferred += len(chunk)
                if declared_length is not None and transferred != int(declared_length):
                    raise RuntimeError("Rapidgator file transfer ended before Content-Length")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("Rapidgator file transfer interrupted") from exc
    size = partial.stat().st_size
    if expected_size is not None and size != expected_size:
        raise RuntimeError(f"Rapidgator file incomplete: {size}/{expected_size} bytes")
    if size == 0:
        raise RuntimeError("Rapidgator returned an empty file")
    partial.replace(target)
    logger.info(f"Rapidgator video saved: {target}")
    return target
