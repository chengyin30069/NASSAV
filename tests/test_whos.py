import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class WhosDownloaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = types.ModuleType("src.downloader.downloaderBase")
        base.Downloader = type("Downloader", (), {})
        base.AVDownloadInfo = types.SimpleNamespace
        cffi = types.ModuleType("curl_cffi")
        cffi.requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=Exception))
        hls = types.ModuleType("src.downloader.missavHls")
        hls.download_media = Mock()
        with patch.dict(sys.modules, {module.__name__: module for module in (base, cffi, hls)}):
            cls.module = importlib.import_module("src.downloader.whosDownloader")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.whosDownloader", None)

    def setUp(self):
        self.downloader = self.module.WhosDownloader()
        self.downloader.domain = "whos.tv"
        self.downloader.path = "/videos"
        self.downloader.proxies = None
        self.downloader.timeout = 15
        self.downloader._fetch_html = Mock()

    def test_reads_only_the_requested_main_player(self):
        self.downloader._fetch_html.return_value = (
            '<meta content="fc2-ppv-4613381 A &amp; B" property="og:title">'
            '<video-player data-id="related"><source src="https://cdn.test/preview.m3u8"></video-player>'
            '<video-player data-id="video-detail-main">'
            '<source src="https://cdn.test/movie.m3u8?a=1&amp;b=2">'
            '</video-player>'
        )
        avid = "FC2-PPV-4613381"
        page = self.downloader.getHTML(avid)
        info = self.downloader.parseHTML(page)
        self.assertEqual(info.avid, avid)
        self.assertEqual(info.title, "A & B")
        self.assertEqual(info.m3u8, "https://cdn.test/movie.m3u8?a=1&b=2")
        page_url = "https://whos.tv/videos/fc2-ppv-4613381"
        self.downloader._fetch_html.assert_called_once_with(page_url)
        self.assertTrue(self.downloader.downloadM3u8(info.m3u8, avid))
        self.module.download_media.assert_called_once_with(
            info.m3u8, Path("/videos/FC2-PPV-4613381/FC2-PPV-4613381.mp4"),
            {"Referer": page_url}, "chrome110",
            proxies=None, timeout=15,
        )

    def test_rejects_page_for_different_code(self):
        self.downloader._fetch_html.return_value = (
            '<meta property="og:title" content="FC2-PPV-46133810 Other">'
            '<video-player data-id="video-detail-main">'
            '<source src="https://cdn.test/other.m3u8"></video-player>'
        )
        self.assertIsNone(self.downloader.parseHTML(self.downloader.getHTML("FC2-PPV-4613381")))


if __name__ == "__main__":
    unittest.main()
