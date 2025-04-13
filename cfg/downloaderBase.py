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
import m3u8
from Crypto.Cipher import AES
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


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

    
    def downloadM3u8(self, url: str, avid: str, max_workers: int = 5) -> bool:
        """
        下载m3u8视频并转换为mp4格式（带进度条）
        :param url: m3u8文件URL
        :param avid: 视频ID
        :param max_workers: 最大并发下载线程数
        :return: 是否成功
        """
        try:
            avid = avid.upper()
            video_dir = os.path.join(self.path, avid)
            temp_dir = os.path.join(project_root, "temp")
            os.makedirs(video_dir, exist_ok=True)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 1. 下载并解析m3u8文件
            with tqdm(desc="下载m3u8文件", unit="B", unit_scale=True) as pbar:
                m3u8_content = self._download_m3u8_with_progress(url, pbar)
            
            if not m3u8_content:
                return False
                
            m3u8_path = os.path.join(temp_dir, f"{avid}.m3u8")
            self._save_file(m3u8_path, m3u8_content)
            
            # 2. 解析TS片段和密钥
            ts_urls, key, iv = self._parse_m3u8(m3u8_path, url)
            if not ts_urls:
                return False
                
            # 3. 下载所有TS片段（带进度条）
            total_size = len(ts_urls)
            with tqdm(total=total_size, desc="下载TS片段", unit="file") as pbar:
                if not self._download_ts_files_with_progress(ts_urls, key, iv, temp_dir, max_workers, pbar):
                    return False
                
            # 4. 合并TS文件并转换为MP4（带进度条）
            output_ts = os.path.join(temp_dir, f"{avid}.ts")
            output_mp4 = os.path.join(video_dir, f"{avid}.mp4")
            
            with tqdm(desc="合并TS文件", unit="B", unit_scale=True) as pbar:
                if not self._merge_ts_files_with_progress(temp_dir, ts_urls, output_ts, pbar):
                    return False
                    
            with tqdm(desc="转换MP4格式", unit="B", unit_scale=True) as pbar:
                if not self._convert_to_mp4_with_progress(output_ts, output_mp4, pbar):
                    return False
                
            # 5. 清理临时文件
            self._cleanup(video_dir, [output_ts, m3u8_path])
            
            return True
            
        except Exception as e:
            logger.error(f"下载m3u8视频失败: {str(e)}")
            return False

    def _parse_m3u8(self, m3u8_path: str, base_url: str) -> tuple:
        """
        解析m3u8文件，返回(ts_urls列表, 解密key, iv)
        """
        try:
            m3u8_obj = m3u8.load(m3u8_path)
            ts_urls = []
            key = None
            iv = None
            
            # 获取TS文件URL
            base_path = os.path.dirname(base_url)
            for segment in m3u8_obj.segments:
                ts_url = segment.uri
                if not ts_url.startswith(('http://', 'https://')):
                    ts_url = f"{base_path}/{ts_url}"
                ts_urls.append(ts_url)
                
            # 获取解密密钥
            if m3u8_obj.keys and m3u8_obj.keys[0]:
                key_uri = m3u8_obj.keys[0].uri
                if not key_uri.startswith(('http://', 'https://')):
                    key_uri = f"{base_path}/{key_uri}"
                    
                key_response = requests.get(key_uri, headers=headers,
                                         proxies=self.proxies, timeout=self.timeout)
                key = key_response.content
                iv = m3u8_obj.keys[0].iv
                if iv:
                    iv = iv.replace("0x", "")[:16].encode()
                    
            return ts_urls, key, iv
            
        except Exception as e:
            logger.error(f"解析m3u8文件失败: {str(e)}")
            return [], None, None


    def _download_m3u8_with_progress(self, url: str, pbar: tqdm) -> Optional[str]:
        """带进度条的m3u8下载"""
        try:
            response = requests.get(url, headers=headers, 
                                 proxies=self.proxies, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            pbar.total = total_size
            pbar.unit = "B"
            pbar.unit_scale = True
            
            content = []
            for data in response.iter_content(chunk_size=1024):
                content.append(data)
                pbar.update(len(data))
                
            return b''.join(content).decode('utf-8')
        except Exception as e:
            logger.error(f"下载m3u8文件失败: {str(e)}")
            return None

    def _download_ts_files_with_progress(self, ts_urls: list[str], key: bytes, iv: bytes, 
                                       output_dir: str, max_workers: int, pbar: tqdm) -> bool:
        """带进度条的并发TS下载"""
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(
                    self._download_ts_file, ts_url, 
                    os.path.join(output_dir, f"segment_{i:04d}.ts"), 
                    key, iv
                ): i for i, ts_url in enumerate(ts_urls)}
                
                for future in as_completed(futures):
                    try:
                        if not future.result():
                            return False
                        pbar.update(1)
                    except Exception as e:
                        logger.error(f"TS下载失败: {str(e)}")
                        return False
            return True
        except Exception as e:
            logger.error(f"下载TS片段失败: {str(e)}")
            return False

    def _download_ts_file(self, ts_url: str, output_path: str, 
                         key: bytes, iv: bytes) -> bool:
        """下载单个TS文件，可选解密"""
        try:
            response = requests.get(ts_url, headers=headers,
                                 proxies=self.proxies, timeout=self.timeout)
            response.raise_for_status()
            
            content = response.content
            if key and iv:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                content = cipher.decrypt(content)
                
            with open(output_path, 'wb') as f:
                f.write(content)
                
            return True
        except Exception as e:
            # logger.error(f"下载TS文件 {ts_url} 失败: {str(e)}")
            return False


    def _merge_ts_files_with_progress(self, video_dir: str, ts_urls: list[str], 
                                    output_path: str, pbar: tqdm) -> bool:
        """带进度条的TS合并"""
        try:
            # 创建文件列表
            list_path = os.path.join(video_dir, "file_list.txt")
            with open(list_path, 'w') as f:
                for i in range(len(ts_urls)):
                    segment_path = os.path.join(video_dir, f"segment_{i:04d}.ts")
                    f.write(f"file '{segment_path}'\n")
                    
            # 使用ffmpeg合并（模拟进度）
            total_files = len(ts_urls)
            command = f"ffmpeg -f concat -i {list_path} -c copy {output_path}"
            
            # 模拟进度（实际ffmpeg进度捕获较复杂）
            for _ in range(total_files):
                pbar.update(1)
                time.sleep(0.1)  # 模拟处理时间
                
            # 实际执行命令
            if os.system(command) != 0:
                return False
                
            # 删除临时文件和分段
            os.remove(list_path)
            for i in range(len(ts_urls)):
                segment_path = os.path.join(video_dir, f"segment_{i:04d}.ts")
                if os.path.exists(segment_path):
                    os.remove(segment_path)
                    
            return True
        except Exception as e:
            logger.error(f"合并TS文件失败: {str(e)}")
            return False

    def _convert_to_mp4_with_progress(self, input_path: str, output_path: str, pbar: tqdm) -> bool:
        """带进度条的MP4转换（模拟）"""
        try:
            # 模拟进度（实际ffmpeg进度捕获较复杂）
            for _ in range(100):
                pbar.update(1)
                time.sleep(0.05)
                
            # 实际执行命令
            command = f"ffmpeg -i {input_path} -c copy -f mp4 {output_path}"
            return os.system(command) == 0
        except Exception as e:
            logger.error(f"转换MP4失败: {str(e)}")
            return False
        
    def _cleanup(self, video_dir: str, files_to_remove: list):
        """清理临时文件"""
        for file_path in files_to_remove:
            if os.path.exists(file_path):
                os.remove(file_path)

    def _save_file(self, path: str, content: str):
        """保存文件"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

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
    
    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            response = requests.get(
                url,
                proxies=self.proxies,
                headers=headers,
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
