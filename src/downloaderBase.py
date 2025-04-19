# doc: 定义下载类的基础操作

from abc import ABC, abstractmethod
import json
from loguru import logger
import os
from dataclasses import dataclass, asdict, field
from typing import Optional, Tuple
from pathlib import Path
from .comm import *
from curl_cffi import requests
from PIL import Image
from datetime import datetime
import time

@dataclass
class AVMetadata:
    m3u8: str = ""
    title: str = ""
    origional_title = ""
    cover: str = ""
    avid: str = ""
    actress: dict = field(default_factory=dict)  # 默认空字典
    description: str = ""
    duration: str = ""
    release_date: str = ""

    def __str__(self):
        return (
            f"=== 元数据详情 ===\n"
            f"番号: {self.avid or '未知'}\n"
            f"标题: {self.title or '未知'}\n"
            f"演员: {self.actress or '未知'}\n"
            f"描述: {self.description or '无'}\n"
            f"封面: {self.cover or '无'}\n"
            f"M3U8: {self.m3u8 or '无'}"
        )

    def to_json(self, file_path: str, indent: int = 2) -> bool:
        try:
            path = Path(file_path) if isinstance(file_path, str) else file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with path.open('w', encoding='utf-8') as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=indent)
            return True
        except (IOError, TypeError) as e:
            logger.error(f"JSON序列化失败: {str(e)}")
            return False

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

class Downloader(ABC):
    """
    使用方式：
    1. downloadMetaData生成元数据，并序列化到metadata.json
    2. downloadM3u8下载视频并转成mp4格式
    3. downloadIMG下载封面和演员头像
    4. genNFO生成nfo文件
    """
    def __init__(self, path: str, proxy = None, timeout = 15):
        """
        :path: 配置的路径，如/vol2/user/missav
        :avid: 车牌号
        """
        self.path = path
        self.proxy = proxy
        self.proxies = {
            'http': proxy,
            'https': proxy
        } if proxy else None
        self.timeout = timeout
    
    def setDomain(self, domain: str) -> bool:
        if domain:  
            self.domain = domain
            return True
        return False

    @abstractmethod
    def getDownloaderName(self) -> str:
        pass

    @abstractmethod
    def getHTML(self, avid: str) -> Optional[str]:
        '''需要实现的方法：根据avid，构造url并请求，获取html, 返回字符串'''
        pass

    @abstractmethod
    def parseHTML(self, html: str, avid: str) -> Optional[AVMetadata]:
        '''
        需要实现的方法：根据html，解析出元数据，返回AVMetadata
        注意：实现新的downloader，只需要获取到m3u8就行了(也可以多匹配点方便调试)，元数据统一使用MissAV
        '''
        pass
    
    def downloadMetaData(self, avid: str) -> Optional[AVMetadata]:
        '''将元数据metadata.json序列化到到对应位置，同时返回AVMetaData'''
        # 获取html
        avid = avid.upper()
        print(os.path.join(self.path, avid))
        os.makedirs(os.path.join(self.path, avid), exist_ok=True)
        html = self.getHTML(avid)
        if not html:
            logger.error("获取html失败")
            return None
        with open(os.path.join(self.path, avid, avid+".html"), "w+") as f:
            f.write(html)

        # 从html中解析元数据，返回MissAVInfo结构体
        metadata = self.parseHTML(html)
        if metadata is None:
            logger.error("解析元数据失败")
            return None
        
        metadata.avid = metadata.avid.upper() # 强制大写
        metadata.to_json(os.path.join(self.path, avid, "metadata.json"))
        logger.info("已保存到 metadata.json")

        return metadata

    
    def downloadM3u8(self, url: str, avid: str) -> bool:
        """m3u8视频下载"""
        os.makedirs(os.path.dirname(os.path.join(self.path, avid)), exist_ok=True)
        try:
            if isNeedVideoProxy and self.proxy:
                logger.info("使用代理")
                command = f"'{project_root}/tools/m3u8-Downloader-Go' -u {url} -o {os.path.join(self.path, avid, avid+'.ts')} -p {self.proxy}"
            else:
                logger.info("不使用代理")
                command = f"'{project_root}/tools/m3u8-Downloader-Go' -u {url} -o {os.path.join(self.path, avid, avid+'.ts')}"
            logger.debug(command)
            if os.system(command) != 0:
                # 难顶。。。使用代理下载失败，尝试不用代理；不用代理下载失败，尝试使用代理
                if not isNeedVideoProxy and self.proxy:
                    logger.info("尝试使用代理")
                    command = f"'{project_root}/tools/m3u8-Downloader-Go' -u {url} -o {os.path.join(self.path, avid, avid+'.ts')} -p {self.proxy}"
                else:
                    logger.info("尝试不使用代理")
                    command = f"'{project_root}/tools/m3u8-Downloader-Go' -u {url} -o {os.path.join(self.path, avid, avid+'.ts')}"
                logger.debug(f"retry {command}")
                if os.system(command) != 0:
                    return False
            
            # 转mp4
            convert = f"ffmpeg -i {os.path.join(self.path, avid, avid+'.ts')} -c copy -f mp4 {os.path.join(self.path, avid, avid+'.mp4')}"
            logger.debug(convert)
            if os.system(convert) != 0:
                return False
            if os.system(f"rm {os.path.join(self.path, avid, avid+'.ts')}") != 0:
                return False
            return True
        except:
            return False
    
    def downloadIMG(self, metadata: AVMetadata) -> bool:
        '''海报+封面+演员头像'''
        # 下载横版海报
        prefix = metadata.avid+"-" # Jellyfin海报格式
        if self._download_file(metadata.cover, metadata.avid+"/"+prefix+"fanart.jpg"):
            # 裁剪竖版封面
            self._crop_img(metadata.avid+"/"+prefix+"fanart.jpg", metadata.avid+"/"+prefix+"poster.jpg")
        else:
            logger.error(f"封面下载失败：{metadata.cover}")
            return False
        # 检查演员是否存在，不存在则下载图像
        for av, url in metadata.actress.items():
            logger.debug(av)
            # 判断是否已经存在
            if os.path.exists(os.path.join(os.path.join(self.path, "thumb", av+".jpg"))):
                continue
            if self._download_file(url, av+".jpg"): # 下载失败，跳过
                continue
            time.sleep(5)
        return True

    def genNFO(self, metadata: AVMetadata) -> bool:
        try:
            date_obj = datetime.strptime(metadata.release_date, '%Y-%m-%d')
            year = date_obj.year
        except (ValueError, TypeError):
            year = ''
        # 添加影片基本信息
        nfo_content = f"""<movie>
    <title>{metadata.avid} {metadata.title}</title>
    <originaltitle>{metadata.origional_title}</originaltitle>
    <year>{year}</year>
    <plot>{metadata.description}</plot>
    <mpaa>R</mpaa>
    <premiered>{metadata.release_date}</premiered>
"""

        # 添加演员信息
        for actress in metadata.actress:
            nfo_content += f"""
    <actor>
        <name>{actress}</name>
        <thumb>{os.path.join(os.path.dirname(self.path), "thumb/"+actress+".jpg")}</thumb>
    </actor>
"""
        
        # 添加艺术图片信息
        nfo_content += f"""
    <art>
        <poster>{metadata.avid}-poster.jpg</poster>
        <fanart>{metadata.avid}-fanart.jpg</fanart>
    </art>
</movie>
"""
        with open(os.path.join(self.path, metadata.avid, metadata.avid+".nfo"), "w+") as f:
            f.write(nfo_content)
        return True

    def _download_file(self, url: str, filename: str) -> bool:
        """通用下载方法，下载到指定位置"""
        try:
            response = requests.get(url, stream=True, impersonate="chrome110", proxies=self.proxies,\
                                    headers=headers,timeout=self.timeout)
            response.raise_for_status()
            
            with open(os.path.join(self.path, filename), 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False
    
    def _fetch_html(self, url: str, referer: str = "") -> Optional[str]:
        try:
            newHeader = headers
            if referer:
                newHeader["Referer"] = referer
            response = requests.get(
                url,
                proxies=self.proxies,
                headers=newHeader,
                timeout=self.timeout,
                impersonate="chrome110",  # 可选：chrome, chrome110, edge99, safari15_5
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {str(e)}")
            return None
    
    def _crop_img(self, srcname, optname):
        img = Image.open(os.path.join(self.path, srcname))
        width, height = img.size
        if height > width:
            return
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
