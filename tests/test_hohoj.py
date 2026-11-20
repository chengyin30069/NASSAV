import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class HohoJDownloaderTest(unittest.TestCase):
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
            cls.module = importlib.import_module("src.downloader.hohoJDownloader")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.hohoJDownloader", None)

    def setUp(self):
        self.downloader = self.module.HohoJDownloader()
        self.downloader.domain = "hohoj.tv"
        self.avid = "FC2-PPV-4575609"

    def test_exact_search_hit_supplies_embed_referer(self):
        self.downloader._fetch_html = Mock(side_effect=[
            '<a href="/video?id=1" title="FC2-PPV-45756090 Other">Wrong</a>'
            '<a href="/video?id=26298"><img alt="fc2-ppv 4575609 A &amp; B"></a>',
            '<script>const videoSrc = "https://media.test/movie.mp4/index.m3u8";</script>',
        ])
        info = self.downloader.parseHTML(self.downloader.getHTML(self.avid))
        self.downloader._fetch_html.assert_called_with(
            "https://hohoj.tv/embed?id=26298", referer="https://hohoj.tv/video?id=26298",
        )
        self.assertEqual(info.avid, self.avid)
        self.assertEqual(info.title, "A & B")
        self.assertEqual(info.m3u8, "https://media.test/movie.mp4/index.m3u8")

    def test_unrelated_links_do_not_open_a_player(self):
        self.downloader._fetch_html = Mock(return_value='<a href="/video?id=1">Other title</a>')
        self.assertIsNone(self.downloader.getHTML(self.avid))
        self.downloader._fetch_html.assert_called_once()


if __name__ == "__main__":
    unittest.main()
