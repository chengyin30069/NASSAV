from .downloaderBase import *
import re

class JableDownloader(Downloader):
    def __init__(self, path: str, proxy = None, timeout = 15, jableDomain = "jable.tv"):
        super().__init__(path, proxy, timeout)
        self.domain = jableDomain

    def getDownloaderName(self) -> str:
        return "Jable"

    def getHTML(self, avid: str) -> Optional[str]:
        '''需要实现的方法：根据avid，构造url并请求，获取html, 返回字符串'''
        url = f'https://{self.domain}/videos/{avid}/'.lower()
        logger.debug(url)
        content = self._fetch_html(url)
        if content: return content
        return None

    def parseHTML(self, html: str) -> Optional[AVMetadata]:
        '''需要实现的方法：根据html，解析出元数据，返回AVMetadata'''
        missavMetadata: AVMetadata = AVMetadata()

        # 1. 提取m3u8
        pattern = r"var hlsUrl = '(https?://[^']+)'"
        match = re.search(pattern, html)
        if match:
            missavMetadata.m3u8 = match.group(1)
            logger.info(missavMetadata.m3u8)
        else:
            logger.error("未找到 m3u8")
            return None

        # 2. 提取基本信息
        if not self._extract_metadata(html, missavMetadata):
            return None

        return missavMetadata

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
    def _extract_metadata(html: str, metadata: AVMetadata) -> bool:
        try:
            # 提取OG标签
            og_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            og_image = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            og_date = re.search(r'(\d{4}-\d{2}-\d{2})', html)

            if og_title: # 处理标题和番号
                title_content = og_title.group(1)
                if code_match := re.search(r'([A-Z]+-\d+)', title_content):
                    metadata.avid = code_match.group(1)
                    metadata.title = title_content.replace(metadata.avid, '').strip()
                else:
                    metadata.title = title_content.strip()

            if og_image:
                metadata.cover = og_image.group(1).strip()

            # 处理发布日期
            if og_date:
                metadata.release_date = og_date.group(1).strip()

        except Exception as e:
            logger.error(f"元数据解析异常: {str(e)}")
            return False

        return True

