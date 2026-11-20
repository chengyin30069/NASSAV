from .downloaderBase import *
import re
from html import unescape
from html.parser import HTMLParser
from typing import Optional, Tuple
from ..cloudflare import browser_headers
from .missavHls import download_media
from .rapidgator import configured_backend, download_rapidgator, extract_rapidgator_link
from urllib.parse import urljoin, urlsplit


class _VideoTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.title:
            attributes = dict(attrs)
            if (attributes.get("property") or "").lower() == "og:title":
                self.title = (attributes.get("content") or "").strip()


class SurritDownloader(Downloader):
    def parseHTML(self, html: str) -> Optional[AVDownloadInfo]:
        metadata = AVDownloadInfo()
        playlist_url = self._extract_playlist_url(html)
        if not playlist_url:
            logger.error(f"{self.getDownloaderName()} 影片頁沒有可用的 HLS 播放清單")
            return None

        result = self._get_highest_quality_m3u8(playlist_url)
        if not result:
            return None
        metadata.m3u8, resolution = result
        logger.debug(f"{self.getDownloaderName()} HLS 畫質: {resolution or '未知'}")

        # 2. 提取基本信息
        if not self._extract_metadata(html, metadata):
            return None

        return metadata

    @classmethod
    def _extract_playlist_url(cls, html: str) -> Optional[str]:
        normalized = html.replace(r"\/", "/")
        for match in re.finditer(
            r"""(?:\bloadSource\(\s*|<source\b[^>]*?\bsrc\s*=\s*)["'](https://[^"'<>\s]+)["']""",
            normalized, re.IGNORECASE,
        ):
            url = unescape(match.group(1))
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.hostname and not parsed.username and parsed.path.lower().endswith(".m3u8"):
                return url
        if uuid := cls._extract_uuid(html):
            return f"https://surrit.com/{uuid}/playlist.m3u8"
        return None

    @staticmethod
    def _extract_uuid(html: str) -> Optional[str]:
        try:
            if match := re.search(r"m3u8\|([a-f0-9\|]+)\|com\|surrit\|https\|video", html):
                return "-".join(match.group(1).split("|")[::-1])
            return None
        except Exception as e:
            logger.error(f"UUID提取异常: {str(e)}")
            return None

    @staticmethod
    def _extract_metadata(html: str, metadata: AVDownloadInfo) -> bool:
        parser = _VideoTitleParser()
        parser.feed(html)
        if not parser.title:
            return False
        code = re.match(r"[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d+(?![A-Z0-9])",
                        parser.title, re.IGNORECASE)
        metadata.avid = code.group().upper() if code else ""
        metadata.title = parser.title[code.end():].strip() if code else parser.title
        return True

    def _media_headers(self) -> dict[str, str]:
        return {"Referer": f"https://{self.domain}/"}

    def _impersonate(self) -> str:
        return "chrome110"

    def _get_highest_quality_m3u8(self, playlist_url: str) -> Optional[Tuple[str, str]]:
        try:
            response = requests.get(
                playlist_url, timeout=self.timeout, proxies=self.proxies,
                headers=self._media_headers(),
                impersonate=self._impersonate(),
            )
            if response.status_code == 403:
                logger.error(f"{self.getDownloaderName()} HLS 初始播放清單遭拒 (HTTP 403, {urlsplit(playlist_url).hostname})")
                return None
            response.raise_for_status()
            lines = [line.strip() for line in response.text.lstrip("\ufeff").splitlines() if line.strip()]
            if not lines or lines[0] != "#EXTM3U":
                raise ValueError("預期收到 #EXTM3U 播放清單")

            streams = []
            for index, line in enumerate(lines[:-1]):
                if not line.startswith("#EXT-X-STREAM-INF:") or lines[index + 1].startswith("#"):
                    continue
                attributes = line.split(":", 1)[1]
                bandwidth = re.search(r"(?:^|,)BANDWIDTH=(\d+)(?:,|$)", attributes)
                resolution = re.search(r"(?:^|,)RESOLUTION=(\d+x\d+)(?:,|$)", attributes)
                if bandwidth:
                    streams.append((int(bandwidth.group(1)),
                                    resolution.group(1) if resolution else "",
                                    lines[index + 1]))

            if streams:
                _, resolution, url = max(streams, key=lambda stream: stream[0])
                return urljoin(response.url, url), resolution
            if any(line.startswith("#EXTINF:") for line in lines):
                return response.url, ""
            raise ValueError("播放清單沒有可用的串流或分段")
        except (ValueError, requests.exceptions.RequestException) as exc:
            logger.error(f"{self.getDownloaderName()} HLS 初始播放清單讀取失敗: {type(exc).__name__}")
            return None

    def downloadM3u8(self, url: str, avid: str) -> bool:
        video_path = os.path.join(self.path, avid, avid + ".mp4")
        try:
            download_media(
                url, video_path, self._media_headers(), self._impersonate(), self.proxies,
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"{self.getDownloaderName()} video download failed: {exc}")
            return False


class MissAVDownloader(SurritDownloader):
    def getDownloaderName(self) -> str:
        return "MissAV"

    def getHTML(self, avid: str) -> Optional[str]:
        '''需要实现的方法：根据avid，构造url并请求，获取html, 返回字符串'''
        for suffix in (f"{avid}-uncensored-leak", f"{avid}-chinese-subtitle", avid):
            url = f"https://{self.domain}/cn/{suffix}".lower()
            content = self._fetch_html(url)
            if content and self._is_target_video_page(content, avid):
                return content
            if content:
                logger.warning(f"略過非 {avid} 影片頁: {url}")

        url = f"https://{self.domain}/dm13/cn/{avid}".lower()
        content = self._fetch_html(url)
        if content and self._is_target_video_page(content, avid):
            return content
        if content:
            logger.warning(f"略過非 {avid} 影片頁: {url}")
        return None

    @classmethod
    def _is_target_video_page(cls, content: str, avid: str) -> bool:
        if not cls._extract_playlist_url(content) and not extract_rapidgator_link(content):
            return False
        parser = _VideoTitleParser()
        parser.feed(content)
        return bool(re.match(rf"^{re.escape(avid)}(?:\W|$)", parser.title, re.IGNORECASE))

    def parseHTML(self, html: str) -> Optional[AVDownloadInfo]:
        '''需要实现的方法：根据html，解析出元数据，返回AVMetadata'''
        self._rapidgator_url = extract_rapidgator_link(html)
        if self._rapidgator_url and configured_backend():
            missavMetadata = AVDownloadInfo()
            missavMetadata.direct_url = self._rapidgator_url
            logger.info("MissAV Rapidgator file link found; using direct file download")
            if not self._extract_metadata(html, missavMetadata):
                return None
            return missavMetadata

        return super().parseHTML(html)

    def _media_headers(self) -> dict[str, str]:
        user_agent = browser_headers(configs.get("Cloudflare", {}), project_root).get("User-Agent")
        media_headers = {"Referer": f"https://{self.domain}/"}
        if user_agent:
            media_headers["User-Agent"] = user_agent
        return media_headers

    def _impersonate(self) -> str:
        return configs.get("Cloudflare", {}).get("Impersonate", "chrome110")

    def downloadM3u8(self, url: str, avid: str) -> bool:
        if not getattr(self, "_rapidgator_url", None) or not configured_backend():
            return super().downloadM3u8(url, avid)
        try:
            download_rapidgator(
                self._rapidgator_url, os.path.join(self.path, avid), avid, self.proxies, self._impersonate(),
            )
            return True
        except (OSError, ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
            logger.error(f"MissAV video download failed: {exc}")
            return False
