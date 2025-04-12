from .downloaderBase import Downloader
# import jableDownloder
from .missAVDownloader import MissAVDownloader
from .comm import *
from typing import Optional

class DownloaderMgr:
    downloaders: dict = {}

    def __init__(self):
        # 注册handler
        downloader = MissAVDownloader(save_path, myproxy, missavDomain=domain)
        self.downloaders[downloader.getDownloaderName()] = downloader
    
    def GetDownloader(self, downloaderName: str) -> Optional[Downloader]:
        return self.downloaders[downloaderName]
