"""Find 7mmtv releases by code and save the main player's HLS as MP4."""

from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import quote, urljoin, urlsplit

from curl_cffi import requests
from loguru import logger

from .downloaderBase import AVDownloadInfo, Downloader
from .missavHls import download_media


_PLAYER_SOURCES = re.compile(
    r"""\{\s*src\s*:\s*['"]([^'"]+)['"]\s*,\s*"""
    r"""type\s*:\s*['"]application/(?:x-mpegurl|vnd\.apple\.mpegurl)['"]\s*,\s*size\s*:\s*(\d+)""",
    re.IGNORECASE,
)


class _SevenMmTvPage(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.links = []
        self.video = None
        self._structured_data = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script":
            self._structured_data = attrs.get("type") == "application/ld+json"

    def handle_endtag(self, tag):
        if tag == "script":
            self._structured_data = False

    def handle_data(self, data):
        if not self._structured_data or self.video is not None:
            return
        try:
            video = json.loads(data)
        except ValueError:
            return
        if isinstance(video, dict) and video.get("@type") == "VideoObject":
            self.video = video


class SevenMmTvDownloader(Downloader):
    def getDownloaderName(self) -> str:
        return "7mmtv"

    def getHTML(self, avid: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", avid):
            return None
        self._avid = avid.upper()
        self._player_url = ""
        base = f"https://{self.domain}/"
        search_code = avid.split("-")[-1] if re.fullmatch(r"FC2-PPV-\d+", self._avid) else avid
        search_url = urljoin(base, f"zh/searchall_search/all/{quote(search_code)}/1.html")
        search = self._fetch_html(search_url)
        if not search:
            return None

        path_pattern = re.compile(
            rf"/zh/[a-z_-]+_content/\d+/{re.escape(avid)}\.html", re.IGNORECASE,
        )
        for link in _SevenMmTvPage(search).links:
            try:
                url = urlsplit(urljoin(base, link))
            except ValueError:
                continue
            if (url.scheme, url.netloc) == ("https", self.domain) and path_pattern.fullmatch(url.path):
                self._detail_url = urljoin(base, url.path)
                return self._fetch_html(self._detail_url, referer=search_url)
        logger.info(f"7mmtv 找不到番號 {self._avid}")
        return None

    def parseHTML(self, html: str) -> AVDownloadInfo | None:
        video = _SevenMmTvPage(html).video
        code = r"[-\s]+".join(map(re.escape, self._avid.split("-")))
        identifier = (video or {}).get("identifier")
        if not isinstance(identifier, str) or not re.fullmatch(code, identifier.strip(), re.IGNORECASE):
            logger.error(f"7mmtv 影片頁與番號 {self._avid} 不符")
            return None

        player_path = video.get("contentUrl")
        if not isinstance(player_path, str):
            logger.error("7mmtv 影片頁沒有主播放器網址")
            return None
        try:
            player_url = urlsplit(urljoin(self._detail_url, player_path))
        except ValueError:
            return None
        if ((player_url.scheme, player_url.netloc) != ("https", self.domain)
                or player_url.path != "/assets/js/play/play.php"):
            logger.error("7mmtv 主播放器網址格式不符")
            return None

        self._player_url = player_url.geturl()
        player = self._fetch_html(self._player_url, referer=self._detail_url)
        if not player:
            return None
        streams = []
        for url, height in _PLAYER_SOURCES.findall(player):
            url = unescape(url)
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                    and parsed.path.lower().endswith(".m3u8")):
                streams.append((int(height), url))
        if not streams:
            logger.error("7mmtv 主播放器沒有公開的 HLS 清單")
            return None
        height, url = max(streams, key=lambda stream: stream[0])
        logger.info(f"7mmtv 選用 {height}p")
        return AVDownloadInfo(m3u8=url, avid=self._avid, title=video.get("name") or "")

    def downloadM3u8(self, url: str, avid: str) -> bool:
        path = Path(self.path) / avid / f"{avid}.mp4"
        try:
            download_media(
                url, path, {"Referer": self._player_url}, "chrome110",
                proxies=self.proxies,
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"7mmtv 影片下載失敗: {exc}")
            return False
