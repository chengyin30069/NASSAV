from .downloaderBase import Downloader
from .jableDownloder import JableDownloader
from .missAVDownloader import MissAVDownloader
from .hohoJDownloader import HohoJDownloader
from .comm import *
from typing import Optional

class DownloaderMgr:
    downloaders: dict = {}

    def __init__(self):
        # 手动注册handler
        downloader = MissAVDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = JableDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = HohoJDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader
    
    def GetDownloader(self, downloaderName: str) -> Optional[Downloader]:
        return self.downloaders[downloaderName]
