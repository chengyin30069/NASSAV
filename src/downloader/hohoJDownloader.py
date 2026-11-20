"""Find exact HohoJ search results and download their HLS media."""

from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from curl_cffi import requests
from loguru import logger

from .downloaderBase import AVDownloadInfo, Downloader
from .missavHls import download_media


class _SearchResult(HTMLParser):
    def __init__(self, html, domain, avid):
        super().__init__()
        code = r"[-\s]+".join(map(re.escape, avid.split("-")))
        self._code = re.compile(rf"^{code}(?!\w)", re.IGNORECASE)
        self._domain = domain
        self._current_id = ""
        self.video_id = ""
        self.title = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self._current_id = ""
            try:
                url = urlsplit(urljoin(f"https://{self._domain}/", attributes.get("href") or ""))
            except ValueError:
                return
            if (url.scheme, url.netloc, url.path.rstrip("/")) == ("https", self._domain, "/video"):
                candidate = parse_qs(url.query).get("id", [""])[0]
                if re.fullmatch(r"[0-9]+", candidate):
                    self._current_id = candidate
        for name in ("title", "alt"):
            if attributes.get(name):
                self._match_title(attributes[name])

    def handle_endtag(self, tag):
        if tag == "a":
            self._current_id = ""

    def handle_data(self, data):
        self._match_title(data)

    def _match_title(self, text):
        if not self._current_id or self.video_id:
            return
        title = text.strip()
        if code := self._code.match(title):
            self.video_id = self._current_id
            self.title = title[code.end():].strip()


class HohoJDownloader(Downloader):
    def getDownloaderName(self) -> str:
        return "HohoJ"

    def getHTML(self, avid: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", avid):
            return None
        self._avid = avid.upper()
        base = f"https://{self.domain}"
        search = self._fetch_html(f"{base}/search?{urlencode({'text': avid})}")
        if not search:
            return None
        result = _SearchResult(search, self.domain, avid)
        if not result.video_id:
            logger.info(f"HohoJ 找不到番號 {avid}")
            return None
        self._title = result.title
        self._embed_url = f"{base}/embed?id={result.video_id}"
        return self._fetch_html(self._embed_url, referer=f"{base}/video?id={result.video_id}")

    def parseHTML(self, html: str) -> AVDownloadInfo | None:
        source = re.search(r"""\b(?:var|let|const)\s+videoSrc\s*=\s*(['"])(.*?)\1""", html)
        if source:
            try:
                url = urljoin(self._embed_url, unescape(source[2]).replace(r"\/", "/"))
                parsed = urlsplit(url)
            except ValueError:
                return None
            if (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                    and parsed.path.lower().endswith(".m3u8")):
                return AVDownloadInfo(m3u8=url, avid=self._avid, title=self._title)
        logger.error("HohoJ 主播放器沒有公開的 HLS 清單")
        return None

    def downloadM3u8(self, url: str, avid: str) -> bool:
        path = Path(self.path) / avid / f"{avid}.mp4"
        try:
            download_media(
                url, path, {"Referer": self._embed_url}, "chrome110",
                proxies=self.proxies, timeout=90,
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"HohoJ 影片下載失敗: {exc}")
            return False
