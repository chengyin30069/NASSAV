import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class SevenMmTvDownloaderTest(unittest.TestCase):
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
            cls.module = importlib.import_module("src.downloader.sevenMmTvDownloader")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.sevenMmTvDownloader", None)

    def setUp(self):
        self.downloader = self.module.SevenMmTvDownloader()
        self.downloader.domain = "7mmtv.sx"
        self.avid = "FC2-PPV-1046668"
        self.search_url = "https://7mmtv.sx/zh/searchall_search/all/1046668/1.html"
        self.detail = "https://7mmtv.sx/zh/uncensored_content/13558/fc2-ppv-1046668.html"

    def test_uses_exact_title_and_highest_declared_hls(self):
        search = (
            '<a href="https://other.test/zh/uncensored_content/13558/fc2-ppv-1046668.html">Other site</a>'
            '<a href="/zh/uncensored_content/31903/fc2-ppv-10466680.html">Other title</a>'
            f'<a href="{self.detail}">Video</a>'
        )
        detail = (
            '<script type="application/ld+json">'
            '{"@type":"VideoObject","identifier":"fc2-ppv 1046668","name":"Sample",'
            '"contentUrl":"//7mmtv.sx/assets/js/play/play.php?example=1"}'
            '</script>'
        )
        player = (
            "{src: 'https://cdn.test/high.m3u8?a=1&b=2', type: 'application/x-mpegURL', size: 720},"
            "{src: 'https://cdn.test/low.m3u8', type: 'application/x-mpegURL', size: 480}"
        )
        self.downloader._fetch_html = Mock(side_effect=[search, detail, player])
        info = self.downloader.parseHTML(self.downloader.getHTML(self.avid))
        self.assertEqual(info.avid, self.avid)
        self.assertEqual(info.m3u8, "https://cdn.test/high.m3u8?a=1&b=2")
        self.assertEqual(self.downloader._fetch_html.call_args_list[1].args, (self.detail,))
        self.assertEqual(self.downloader._fetch_html.call_args_list[1].kwargs, {"referer": self.search_url})
        self.downloader._fetch_html.assert_called_with(
            "https://7mmtv.sx/assets/js/play/play.php?example=1", referer=self.detail,
        )

    def test_rejects_mismatched_structured_identifier(self):
        self.downloader._fetch_html = Mock(side_effect=[
            f'<a href="{self.detail}">Video</a>',
            '<script type="application/ld+json">'
            '{"@type":"VideoObject","identifier":"fc2-ppv 10466680",'
            '"contentUrl":"//7mmtv.sx/assets/js/play/play.php"}'
            '</script>',
        ])
        self.assertIsNone(self.downloader.parseHTML(self.downloader.getHTML(self.avid)))
        self.assertEqual(self.downloader._fetch_html.call_count, 2)


if __name__ == "__main__":
    unittest.main()
