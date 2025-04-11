from curl_cffi import requests
from .comm import *
from typing import Optional, Dict, Tuple
import re
from mutagen.mp4 import MP4, MP4Cover
import os
from PIL import Image
from datetime import datetime

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

# 元数据抓取器
class MissAVMetaDataScraper:
    def __init__(
        self,
        proxy: Optional[str] = "http://127.0.0.1:7897",
        timeout: int = 15
    ):
        self.proxies = {
            'http': proxy,
            'https': proxy
        } if proxy else None
        
        self.timeout = timeout
        self.headers = headers

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            response = requests.get(
                url,
                proxies=self.proxies,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {str(e)}")
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
    def _extract_metadata(html: str) -> Dict[str, str]:
        metadata = {
            'title': '',
            'description': '',
            'cover': '',
            'identity': '',
            'actress': '',
            'duration': '',
            'release_date': '',
            'origional_title': ''
        }

        try:
            # 提取OG标签
            og_title = re.search(r'<meta property="og:title" content="(.*?)"', html)
            og_desc = re.search(r'<meta property="og:description" content="(.*?)"', html)
            og_image = re.search(r'<meta property="og:image" content="(.*?)"', html)
            og_duration = re.search(r'<meta property="og:video:duration" content="(\d+)"', html)
            og_date = re.search(r'<meta property="og:video:release_date" content="(.*?)"', html)

            # 处理标题和番号
            if og_title:
                title_content = og_title.group(1)
                if code_match := re.search(r'([A-Z]+-\d+)', title_content):
                    metadata['identity'] = code_match.group(1)
                    metadata['title'] = title_content.replace(metadata['identity'], '').strip()
                else:
                    metadata['title'] = title_content.strip()
            
            # 处理原标题
            matches_group = re.search(r'<span>标题:</span>\s*<span class="font-medium">(.+)</span>', html)
            if matches_group:
                metadata['origional_title'] = matches_group.group(1)
                logger.debug(metadata['origional_title'])


            # 处理演员（假设格式为"标题 - 演员"）
            if og_title and ' - ' in og_title.group(1):
                metadata['actress'] = og_title.group(1).split(' - ')[-1].strip()

            # 其他直接映射的字段
            if og_desc:
                metadata['description'] = og_desc.group(1).strip()
            if og_image:
                metadata['cover'] = og_image.group(1).strip()

            # 处理视频时长（秒转分钟）
            if og_duration:
                seconds = int(og_duration.group(1))
                metadata['duration'] = f"{seconds // 60}分{seconds % 60}秒"

            # 处理发布日期
            if og_date:
                metadata['release_date'] = og_date.group(1).strip()

        except Exception as e:
            logger.error(f"元数据解析异常: {str(e)}")

        return metadata
    
    @staticmethod
    def _get_highest_quality_m3u8(playlist_url: str) -> Optional[Tuple[str, str]]:
        try:
            response = requests.get(playlist_url, timeout=10)
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

    def scrape(self, url: str) -> Optional[MissAVInfo]:
        if not url.startswith(('http://', 'https://')):
            logger.error(f"无效URL格式: {url}")
            return None

        if html := self._fetch_html(url):
            info = MissAVInfo()
            if uuid := self._extract_uuid(html):
                playlist_url = f"https://surrit.com/{uuid}/playlist.m3u8"
                result = self._get_highest_quality_m3u8(playlist_url)
                if result:
                    m3u8_url, resolution = result
                    logger.debug(f"最高清晰度: {resolution}")
                    logger.debug(f"M3U8链接: {m3u8_url}")
                    info.m3u8 = m3u8_url
                else:
                    logger.error("未找到有效视频流")

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
                            logger.debug(f"图片链接: {img}")
                            logger.debug(f"小姐姐: {actress}")
                            info.actress[actress] = img
                        else:
                            logger.error("未匹配到内容")
                    except:
                        logger.error(f"演员信息:{url} 提取失败")
                        continue

            # 提取其他元数据
            metadata = self._extract_metadata(html)
            info.title = metadata.get('title', '')
            info.identity = metadata.get('identity', '')
            # info.actress = metadata.get('actress', '')
            info.description = metadata.get('description', '')
            info.cover = metadata.get('cover', '')
            info.duration = metadata.get('duration', '')
            info.release_date = metadata.get('release_date', '')
            info.origional_title = metadata.get('origional_title', '')

            return info
        
        return None

# 资源下载器
class AssertDownloader:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(path, exist_ok=True)
    
    def _download_file(self, url: str, filename: str) -> bool:
        """通用下载方法"""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(os.path.join(self.path, filename), 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False
    
    def _crop_img(self, srcname, optname):
        # 打开图片
        img = Image.open(os.path.join(self.path, srcname))
        width, height = img.size
        if height > width:
            return

        # 计算目标尺寸（9:16 比例）
        target_width = int(height * 565 / 800)

        # 从右侧开始裁剪
        left = width - target_width  # 右侧起点
        right = width
        top = 0
        bottom = height

        # 裁剪并保存
        cropped_img = img.crop((left, top, right, bottom))
        cropped_img.save(os.path.join(self.path, optname))
        logger.debug(f"裁剪完成，尺寸: {cropped_img.size}")


    def ImgDownloader(self, url: str, prefix="") -> bool:
        """图片下载，填充元数据时会自动下载图片"""
        if self._download_file(url, prefix+"fanart.jpg"):
            self._crop_img(prefix+"fanart.jpg", prefix+"poster.jpg") # 只保留竖版封面
            return True
        return False

    def M3u8Downloader(self, url: str, title: str) -> bool:
        """m3u8视频下载"""
        try:
            command = f"'{project_root}/tools/m3u8-Downloader-Go' -u {url} -o {os.path.join(self.path, title+'.ts')} -p http://127.0.0.1:7897"
            logger.debug(command)
            if os.system(command) != 0:
                return False
            # 转mp4
            convert = f"ffmpeg -i {os.path.join(self.path, title+'.ts')} -c copy -f mp4 {os.path.join(self.path, title+'.mp4')}"
            logger.debug(convert)
            if os.system(convert) != 0:
                return False;
            if os.system(f"rm {os.path.join(self.path, title+'.ts')}") != 0:
                return False
            return True
        except:
            return False

    def MetaDataInserter(self, video_path: str, metadata: MissAVInfo) -> bool:
        try:
            # 下载封面图片
            cover_path = None
            if metadata.cover:
                cover_path = os.path.join(self.path, metadata.identity+"-fanart.jpg")
                if not self.ImgDownloader(metadata.cover, metadata.identity+'-'):
                    logger.error(f"封面下载失败: {metadata.cover}")
                    cover_path = None
            
            # 初始化MP4元数据处理器
            mp4 = MP4(video_path)
            
            if metadata.title:
                mp4["\xa9nam"] = f"{metadata.identity} {metadata.actress} {metadata.title}"
            if metadata.actress:
                mp4["\xa9ART"] = metadata.actress.split(",") if "," in metadata.actress else metadata.actress
            if metadata.identity:
                mp4["----:com.apple.iTunes:Identity"] = metadata.identity.encode('utf-8')
            if metadata.description:
                mp4["\xa9des"] = metadata.description
                mp4["desc"] = metadata.description
                mp4["©cmt"] = metadata.description
            if metadata.duration:
                try:
                    # 假设格式为 "HH:MM:SS" 或 "MM:SS"
                    parts = list(map(int, metadata.duration.split(":")))
                    if len(parts) == 3:  # HH:MM:SS
                        total_seconds = parts[0]*3600 + parts[1]*60 + parts[2]
                    elif len(parts) == 2:  # MM:SS
                        total_seconds = parts[0]*60 + parts[1]
                    else:
                        total_seconds = int(metadata.duration)  # 直接是秒数
                    mp4["\xa9day"] = str(total_seconds)
                except (ValueError, AttributeError):
                    pass
            if metadata.release_date:
                mp4["\xa9day"] = metadata.release_date
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, 'rb') as f:
                        cover_data = f.read()
                    mp4["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
                except Exception as e:
                    logger.error(f"封面嵌入失败: {e}")
            
            mp4.save()
            return True
            
        except Exception as e:
            logger.error(f"元数据嵌入失败: {e}")
            return False

# nfo生成器（实际上就是xml）
class NfoGenerator:
    def __init__(self, path: str):
        with open(os.path.join(path, "metadata.json"), 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        self.path = path
        self.id = metadata.get('identity', '')
        self.title = metadata.get('title', '')
        self.originaltitle = metadata.get('originaltitle', '')
        self.release_date = metadata.get('release_date', '')
        self.actresses = metadata.get('actress', [])
        self.description = metadata.get('description', '')
        try:
            date_obj = datetime.strptime(self.release_date, '%Y-%m-%d')
            self.year = date_obj.year
        except (ValueError, TypeError):
            self.year = ''

    def GenXML(self):
        nfo_content = f"""<movie>
    <title>{self.id} {self.title}</title>
    <originaltitle>{self.originaltitle}</originaltitle>
    <year>{self.year}</year>
    <plot>{self.description}</plot>
    <mpaa>R</mpaa>
    <premiered>{self.release_date}</premiered>
"""

        # 添加演员信息
        for actress in self.actresses:
            nfo_content += f"""
    <actor>
        <name>{actress}</name>
        <thumb>{os.path.join(os.path.dirname(self.path), "thumb/"+actress+".jpg")}</thumb>
    </actor>
"""
        
        # 添加艺术图片信息
        nfo_content += f"""
    <art>
        <poster>{self.id}-poster.jpg</poster>
        <fanart>{self.id}-fanart.jpg</fanart>
    </art>
</movie>
"""
        with open(os.path.join(self.path, self.id+".nfo"), "w+") as f:
            f.write(nfo_content)

if __name__ == "__main__":
    scraper = MissAVMetaDataScraper()
    # 测试抓取
    sample_url = f"https://{domain}/cn/mfo-077"
    if result := scraper.scrape(sample_url):
        logger.debug("抓取成功:")
        logger.debug(result)
    else:
        logger.error("抓取失败，请检查日志")

    result.to_json("metadata.json")
    logger.info("已保存到 metadata.json")