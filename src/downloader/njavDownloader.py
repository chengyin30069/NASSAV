"""Resolve NJAV's video pages through the shared Surrit downloader."""

import re

from loguru import logger

from .downloaderBase import AVDownloadInfo
from .missAVDownloader import SurritDownloader


class NjavDownloader(SurritDownloader):
    def getDownloaderName(self) -> str:
        return "NJAV"

    def getHTML(self, avid: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", avid):
            return None
        url = f"https://{self.domain}/en/{avid.lower()}"
        html = self._fetch_html(url)
        if not html:
            return None
        metadata = AVDownloadInfo()
        if not self._extract_metadata(html, metadata) or metadata.avid != avid.upper():
            logger.warning(f"NJAV 影片頁與番號 {avid} 不符")
            return None
        return html
