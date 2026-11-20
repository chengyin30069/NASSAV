from .downloader.downloaderBase import Downloader
from .downloader.jableDownloder import JableDownloader
from .downloader.missAVDownloader import MissAVDownloader
from .downloader.hohoJDownloader import HohoJDownloader
from .downloader.memoDownloader import MemoDownloader
from .downloader.javhdpornDownloader import JavHDPornDownloader
from .downloader.whosDownloader import WhosDownloader
from .downloader.sevenMmTvDownloader import SevenMmTvDownloader
from .downloader.njavDownloader import NjavDownloader
from .downloader.oneTwoThreeAvDownloader import OneTwoThreeAvDownloader
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

        downloader = MemoDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = JavHDPornDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = WhosDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = SevenMmTvDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = NjavDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader

        downloader = OneTwoThreeAvDownloader(save_path, myproxy)
        self.downloaders[downloader.getDownloaderName()] = downloader
    
    def GetDownloader(self, downloaderName: str) -> Optional[Downloader]:
        return self.downloaders.get(downloaderName)
