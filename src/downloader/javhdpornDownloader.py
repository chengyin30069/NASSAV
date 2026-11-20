"""Resolve JAV HD Porn search results and download the main player's media."""

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urljoin, urlsplit

from loguru import logger

from ..browser import browser_environment as _browser_environment
from .downloaderBase import AVDownloadInfo, Downloader


def _media_url(base, value):
    try:
        url = urljoin(base, value)
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme == "https" and parts.hostname and parts.username is None and
            Path(parts.path).suffix.lower() in (".m3u8", ".mp4")):
        return url
    return None


def _title_prefix(avid):
    code = r"[-\s]+".join(map(re.escape, avid.split("-")))
    return re.compile(rf"^{code}(?!\w)", re.IGNORECASE)


class _VideoPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.title = ""
        self.sources = []
        self.player_depth = 0
        self.has_script_player = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "meta" and attrs.get("property") == "og:title" and not self.title:
            self.title = (attrs.get("content") or "").strip()
        if tag == "div":
            if attrs.get("id") == "video-player":
                self.player_depth = 1
                self.has_script_player = bool(attrs.get("data-mpu"))
            elif self.player_depth:
                self.player_depth += 1
        if self.player_depth and tag in ("video", "source") and attrs.get("src"):
            self.sources.append(attrs["src"])

    def handle_endtag(self, tag):
        if tag == "div" and self.player_depth:
            self.player_depth -= 1


class JavHDPornDownloader(Downloader):
    use_page_solver = True

    def getDownloaderName(self) -> str:
        return "JavHDPorn"

    def getHTML(self, avid: str) -> str | None:
        self._avid = avid.upper()
        self._page_url = ""
        self._media_referer = ""
        self._user_agent = ""
        if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", self._avid):
            return None
        title_prefix = _title_prefix(self._avid)
        base = f"https://{self.domain}/"
        search_url = base + "?" + urlencode({"s": avid})
        search = self._fetch_html(search_url)
        candidates = {}
        if search:
            for href in _VideoPage(search).links:
                try:
                    url = urlsplit(urljoin(base, href))
                except ValueError:
                    continue
                slug = re.fullmatch(r"/(?:v\d+/)?video/([^/]+)/?", url.path)
                if (url.scheme == "https" and url.netloc == self.domain and slug and
                        re.match(rf"^{re.escape(avid)}(?:-|$)", slug[1], re.IGNORECASE)):
                    candidates[url.path] = urljoin(base, url.path)

        direct_path = f"/video/{avid.lower()}/"
        candidates.setdefault(direct_path, urljoin(base, direct_path))
        for url in candidates.values():
            html = self._fetch_html(url, referer=search_url)
            if html and title_prefix.match(_VideoPage(html).title):
                self._page_url = url
                return html
        return None

    def parseHTML(self, html: str) -> AVDownloadInfo | None:
        page = _VideoPage(html)
        self._media_referer = self._page_url
        url = next((url for source in page.sources if (url := _media_url(self._page_url, source))), None)
        if not url and page.has_script_player:
            url = self._play_in_browser()
        if not url:
            logger.error("JavHDPorn 主播放器沒有可用的 HLS 或 MP4 來源")
            return None
        return AVDownloadInfo(m3u8=url, avid=self._avid,
                              title=_title_prefix(self._avid).sub("", page.title, count=1).strip())

    def _play_in_browser(self):
        try:
            from selenium import webdriver
            from selenium.common.exceptions import NoSuchFrameException, StaleElementReferenceException, WebDriverException
            from selenium.webdriver.common.by import By
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            logger.error("JavHDPorn 動態播放器需要 Docker 映像內的 Chromium 和 Selenium")
            return None

        options = webdriver.ChromeOptions()
        options.page_load_strategy = "none"
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        for flag in ("--disable-dev-shm-usage", "--window-size=1280,900"):
            options.add_argument(flag)
        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy}")
        # Chromium's sandbox is unavailable in the default NASSAV container.
        if Path("/.dockerenv").exists():
            options.add_argument("--no-sandbox")
        try:
            with _browser_environment() as environment:
                if not environment.get("DISPLAY") and os.name != "nt":
                    options.add_argument("--headless=new")
                service = Service(env=environment)
                with webdriver.Chrome(options=options, service=service) as browser:
                    browser.set_page_load_timeout(self.timeout)
                    browser.get(self._page_url)
                    wait = WebDriverWait(browser, self.timeout, ignored_exceptions=(
                        NoSuchFrameException, StaleElementReferenceException,
                    ))
                    button = wait.until(lambda driver: driver.find_element(By.CSS_SELECTOR, "#video-player .play-button"))
                    browser.execute_script("performance.clearResourceTimings()")
                    browser.get_log("performance")
                    button.click()
                    try:
                        url, referer, user_agent = wait.until(self._read_playing_source)
                    except (RuntimeError, WebDriverException):
                        self._log_embed_denial(browser)
                        raise
            self._media_referer = referer or self._page_url
            self._user_agent = user_agent
            return url
        except (OSError, WebDriverException) as exc:
            logger.error(f"JavHDPorn 瀏覽器播放未取得來源 ({type(exc).__name__})")
            return None
        except RuntimeError as exc:
            logger.error(f"JavHDPorn 瀏覽器播放失敗: {exc}")
            return None

    @staticmethod
    def _log_embed_denial(browser):
        for entry in browser.get_log("performance"):
            event = json.loads(entry["message"])["message"]
            if event["method"] != "Network.responseReceived":
                continue
            params = event["params"]
            response = params["response"]
            url = urlsplit(response["url"])
            if params["type"] != "Document" or url.hostname != "video.javhdporn.net":
                continue
            if response["status"] in (401, 403):
                headers = {key.lower(): value for key, value in response["headers"].items()}
                challenge = "，Cloudflare challenge" if headers.get("cf-mitigated") == "challenge" else ""
                logger.error(f"JavHDPorn 內嵌頁遭拒 (HTTP {response['status']}，{url.hostname}{url.path}{challenge})")
                return

    @staticmethod
    def _read_playing_source(browser):
        def read(selector):
            base, user_agent, sources = browser.execute_script(r"""
                if (location.protocol === 'chrome-error:') {
                    return [null, '', []];
                }
                const elements = [...document.querySelectorAll(arguments[0])];
                const sources = elements.flatMap(e => [e.currentSrc, e.src]);
                if (elements.length) {
                    sources.push(...performance.getEntriesByType('resource')
                        .filter(r => /\.m3u8(?:[?#]|$)/i.test(r.name)
                            && (r.responseStatus === 0 || (r.responseStatus >= 200 && r.responseStatus < 300)))
                        .map(r => r.name));
                }
                const base = location.protocol === 'https:' ? location.href : document.referrer;
                return [base, navigator.userAgent, sources.filter(Boolean)];
            """, selector)
            if base is None:
                raise RuntimeError("Chromium 無法載入主播放器或其內嵌頁面")
            for source in sources:
                if url := _media_url(base, source):
                    return url, base, user_agent
            return None

        source = read("#video-player video, #video-player video source")
        if source:
            return source
        for frame in browser.find_elements("css selector", "#video-player iframe"):
            browser.switch_to.frame(frame)
            try:
                if source := read("video, video source"):
                    return source
            finally:
                browser.switch_to.default_content()
        return None

    def downloadM3u8(self, url: str, avid: str) -> bool:
        output = Path(self.path) / avid / f"{avid}.mp4"
        try:
            if output.exists():
                raise FileExistsError(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".javhdporn-", dir=output.parent) as directory:
                temporary = Path(directory) / output.name
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-xerror",
                    "-rw_timeout", str(self.timeout * 1_000_000),
                    "-protocol_whitelist", "http,https,tcp,tls,crypto,httpproxy",
                    "-referer", self._media_referer or self._page_url,
                ]
                if self._user_agent:
                    command.extend(["-user_agent", self._user_agent])
                if self.proxy:
                    command.extend(["-http_proxy", self.proxy])
                command.extend([
                    "-i", url, "-map", "0:v:0", "-map", "0:a:0?",
                    "-c", "copy", str(temporary),
                ])
                result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                status = re.search(r"HTTP error (\d{3})|Server returned (\d{3})", result.stderr)
                missing_segment = "Failed to open segment" in result.stderr
                if (result.returncode or status or missing_segment or
                        not temporary.is_file() or not temporary.stat().st_size):
                    detail = f"HTTP {status.group(1) or status.group(2)}" if status else "媒體不完整"
                    logger.error(f"JavHDPorn 影片下載失敗 ({detail})")
                    return False
                if output.exists():
                    raise FileExistsError(output)
                temporary.replace(output)
            return True
        except OSError as exc:
            logger.error(f"JavHDPorn 影片儲存失敗: {exc}")
            return False
