"""Resolve the HLS source loaded by 123AV's embedded player."""

import os
from pathlib import Path
import re

from curl_cffi import requests
from loguru import logger

from ..browser import browser_environment
from .downloaderBase import AVDownloadInfo, Downloader
from .missAVDownloader import _VideoTitleParser
from .missavHls import download_media


class OneTwoThreeAvDownloader(Downloader):
    def getDownloaderName(self) -> str:
        return "123AV"

    def getHTML(self, avid: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", avid):
            return None
        self._avid = avid.upper()
        self._page_url = f"https://{self.domain}/en/v/{avid.lower()}"
        return self._fetch_html(self._page_url)

    def parseHTML(self, html: str) -> AVDownloadInfo | None:
        title = _VideoTitleParser()
        title.feed(html)
        prefix = re.match(rf"^{re.escape(self._avid)}(?!\w)", title.title, re.IGNORECASE)
        if not prefix:
            logger.warning(f"123AV 影片頁與番號 {self._avid} 不符")
            return None
        source = self._resolve_player()
        if not source:
            return None
        return AVDownloadInfo(
            m3u8=source, avid=self._avid, title=title.title[prefix.end():].lstrip(" —–-"),
        )

    def _resolve_player(self) -> str | None:
        try:
            from selenium import webdriver
            from selenium.common.exceptions import WebDriverException
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            logger.error("123AV 需要 Chromium 和 Selenium")
            return None

        try:
            with browser_environment() as environment:
                options = webdriver.ChromeOptions()
                options.page_load_strategy = "none"
                options.add_argument("--disable-dev-shm-usage")
                if Path("/.dockerenv").exists():
                    options.add_argument("--no-sandbox")
                if not environment.get("DISPLAY") and os.name != "nt":
                    options.add_argument("--headless=new")
                if self.proxy:
                    options.add_argument(f"--proxy-server={self.proxy}")
                with webdriver.Chrome(options=options, service=Service(env=environment)) as browser:
                    wait = WebDriverWait(browser, self.timeout)
                    browser.get(self._page_url)
                    frame = wait.until(lambda driver: driver.find_element(By.CSS_SELECTOR, "iframe.player__frame"))
                    browser.switch_to.frame(frame)
                    checked = set()

                    def selected_media(driver):
                        referer, user_agent, urls = self._player_playlists(driver)
                        if not referer.startswith("https://"):
                            return None
                        self._media_headers = {"Referer": referer, "User-Agent": user_agent}
                        for url in reversed(urls):
                            if url in checked or not url.startswith("https://"):
                                continue
                            checked.add(url)
                            if self._is_media_playlist(url):
                                return url
                        return None

                    return wait.until(selected_media)
        except (OSError, WebDriverException) as exc:
            logger.error(f"123AV 無法讀取主播放器 ({type(exc).__name__})")
            return None

    @staticmethod
    def _player_playlists(browser):
        return browser.execute_script(r"""
            const urls = performance.getEntriesByType('resource')
                .filter(entry => (entry.responseStatus === 0 || entry.responseStatus === 200)
                    && /\.m3u8$/i.test(new URL(entry.name).pathname))
                .map(entry => entry.name);
            return [location.href, navigator.userAgent, [...new Set(urls)]];
        """)

    def _is_media_playlist(self, url: str) -> bool:
        try:
            response = requests.get(
                url, headers=self._media_headers, impersonate="chrome110",
                proxies=self.proxies, timeout=self.timeout,
            )
        except requests.exceptions.RequestException:
            return False
        return (response.ok and response.text.lstrip("\ufeff").startswith("#EXTM3U")
                and "#EXTINF:" in response.text and "#EXT-X-STREAM-INF:" not in response.text)

    def downloadM3u8(self, url: str, avid: str) -> bool:
        output = Path(self.path) / avid / f"{avid}.mp4"
        try:
            download_media(
                url, output, self._media_headers, "chrome110", proxies=self.proxies,
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"123AV 影片下載失敗: {exc}")
            return False
