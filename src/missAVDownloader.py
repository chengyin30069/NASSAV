from .downloaderBase import *
import re
from typing import Optional, Tuple

class MissAVDownloader(Downloader):
    def getDownloaderName(self) -> str:
        return "MissAV"

    def getHTML(self, avid: str) -> Optional[str]:
        '''需要实现的方法：根据avid，构造url并请求，获取html, 返回字符串'''
        url = f'https://{self.domain}/cn/{avid}-uncensored-leak'.lower()
        content = self._fetch_html(url)
        if content: return content

        url = f'https://{self.domain}/cn/{avid}-chinese-subtitle'.lower()
        content = self._fetch_html(url)
        if content: return content

        url = f'https://{self.domain}/cn/{avid}'.lower()
        content = self._fetch_html(url)
        if content: return content

        return None

    def parseHTML(self, html: str) -> Optional[AVMetadata]:
        '''需要实现的方法：根据html，解析出元数据，返回AVMetadata'''
        missavMetadata: AVMetadata = AVMetadata()

        # 1. 提取m3u8
        if uuid := self._extract_uuid(html):
            playlist_url = f"https://surrit.com/{uuid}/playlist.m3u8"
            result = self._get_highest_quality_m3u8(playlist_url)
            if result:
                m3u8_url, resolution = result
                logger.debug(f"最高清晰度: {resolution}\nM3U8链接: {m3u8_url}")
                missavMetadata.m3u8 = m3u8_url
            else:
                logger.error("未找到有效视频流")
                return None
        else:
            logger.error("未找到有效uuid")
            return None

        # 2. 提取基本信息
        if not self._extract_metadata(html, missavMetadata):
            return None
        
        # 3. 提取演员信息
        self._extract_actress(html, missavMetadata)

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
            og_title = re.search(r'<meta property="og:title" content="(.*?)"', html)
            og_desc = re.search(r'<meta property="og:description" content="(.*?)"', html)
            og_image = re.search(r'<meta property="og:image" content="(.*?)"', html)
            og_duration = re.search(r'<meta property="og:video:duration" content="(\d+)"', html)
            og_date = re.search(r'<meta property="og:video:release_date" content="(.*?)"', html)

            if og_title: # 处理标题和番号
                title_content = og_title.group(1)
                if code_match := re.search(r'([A-Z]+-\d+)', title_content):
                    metadata.avid = code_match.group(1)
                    metadata.title = title_content.replace(metadata.avid, '').strip()
                else:
                    metadata.title = title_content.strip()
            
            # 处理原标题
            matches_group = re.search(r'<span>标题:</span>\s*<span class="font-medium">(.+)</span>', html)
            if matches_group:
                metadata.origional_title = matches_group.group(1)
                logger.debug(metadata.origional_title)

            # 其他直接映射的字段
            if og_desc:
                metadata.description = og_desc.group(1).strip()
            if og_image:
                metadata.cover = og_image.group(1).strip()

            # 处理视频时长（秒转分钟）
            if og_duration:
                seconds = int(og_duration.group(1))
                metadata.duration = f"{seconds // 60}分{seconds % 60}秒"

            # 处理发布日期
            if og_date:
                metadata.release_date = og_date.group(1).strip()

        except Exception as e:
            logger.error(f"元数据解析异常: {str(e)}")
            return False

        return True
    
    @staticmethod
    def _get_highest_quality_m3u8(playlist_url: str) -> Optional[Tuple[str, str]]:
        try:
            response = requests.get(playlist_url, timeout=10, impersonate="chrome110")
            response.raise_for_status()
            playlist_content = response.text
            
            streams = []
            pattern = re.compile(
                r'#EXT-X-STREAM-INF:BANDWIDTH=(\d+),.*?RESOLUTION=(\d+x\d+).*?\n(.*)'
            )
            
            for match in pattern.finditer(playlist_content):
                bandwidth = int(match.group(1))
                resolution = match.group(2)
                url = match.group(3).strip()
                streams.append((bandwidth, resolution, url))
            
            # 按带宽降序排序
            streams.sort(reverse=True, key=lambda x: x[0])
            logger.debug(streams)
            
            if streams:
                # 返回最高质量的流
                best_stream = streams[0]
                base_url = playlist_url.rsplit('/', 1)[0]  # 获取基础URL
                full_url = f"{base_url}/{best_stream[2]}" if not best_stream[2].startswith('http') else best_stream[2]
                return full_url, best_stream[1]      
            return None
        
        except Exception as e:
            logger.error(f"获取最高质量流失败: {str(e)}")
            return None
        
    def _extract_actress(self, html: str, metadata: AVMetadata):
        '''没有找到，跳过而不是返回'''
        # 提取演员信息元数据
        matches = re.findall(r'<span>女优:</span>\s*<a.*</a>', html)
        for match in matches:
            urls = re.findall(r'<a href="([^"]+)"[^>]*>', match)
            for url in urls:
                try: 
                    logger.debug(url)
                    content = self._fetch_html(url)
                    pattern = r'<img\s+src="(https://fourhoi\.com/actress/[^"]+)"\s+alt="([^"]+)"'
                    match_group = re.search(pattern, content)
                    if match_group:
                        img = match_group.group(1)  # 图片链接
                        actress = match_group.group(2)   # alt文本
                        logger.debug(f"图片链接: {img}\n小姐姐: {actress}")
                        metadata.actress[actress] = img
                    else:
                        logger.error("未匹配到内容")
                    time.sleep(5)
                except:
                    logger.error(f"演员信息:{url} 提取失败")
                    continue

