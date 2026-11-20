"""Download the main HLS stream from a Whos.tv video detail page."""

from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

from curl_cffi import requests
from loguru import logger

from .downloaderBase import AVDownloadInfo, Downloader
from .missavHls import download_media


class _WhosVideoPage(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.title = ""
        self.playlist = ""
        self.in_main_player = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("property") == "og:title" and not self.title:
            self.title = (attributes.get("content") or "").strip()
        if tag == "video-player":
            self.in_main_player = attributes.get("data-id") == "video-detail-main"
        if tag != "source" or not self.in_main_player or self.playlist:
            return
        source = attributes.get("src") or ""
        try:
            url = urlsplit(source)
        except ValueError:
            return
        if (url.scheme == "https" and url.hostname and url.username is None
                and url.path.lower().endswith(".m3u8")):
            self.playlist = source

    def handle_endtag(self, tag):
        if tag == "video-player":
            self.in_main_player = False


class WhosDownloader(Downloader):
    def getDownloaderName(self) -> str:
        return "Whos"

    def _video_url(self, avid: str) -> str:
        return f"https://{self.domain}/videos/{avid.lower()}"

    def getHTML(self, avid: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", avid):
            return None
        self._avid = avid.upper()
        return self._fetch_html(self._video_url(avid))

    def parseHTML(self, html: str) -> AVDownloadInfo | None:
        page = _WhosVideoPage(html)
        code = re.match(rf"^{re.escape(self._avid)}(?!\w)", page.title, re.IGNORECASE)
        if not code:
            logger.error(f"Whos.tv 影片頁與番號 {self._avid} 不符")
            return None
        if not page.playlist:
            logger.error("Whos.tv 主播放器沒有公開的 HLS 清單")
            return None
        return AVDownloadInfo(m3u8=page.playlist, avid=self._avid, title=page.title[code.end():].strip())

    def downloadM3u8(self, url: str, avid: str) -> bool:
        path = Path(self.path) / avid / f"{avid}.mp4"
        try:
            download_media(
                url, path, {"Referer": self._video_url(avid)}, "chrome110",
                proxies=self.proxies, timeout=self.timeout,
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"Whos.tv 影片下載失敗: {exc}")
            return False
