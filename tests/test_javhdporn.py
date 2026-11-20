import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class JavHDPornTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = types.ModuleType("src.downloader.downloaderBase")
        base.Downloader = type("Downloader", (), {})
        base.AVDownloadInfo = types.SimpleNamespace
        with patch.dict(sys.modules, {base.__name__: base}):
            cls.module = importlib.import_module("src.downloader.javhdpornDownloader")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.javhdpornDownloader", None)

    def setUp(self):
        self.downloader = self.module.JavHDPornDownloader()
        self.downloader.domain = "www.javhdporn.net"

    def test_search_matches_exact_code_and_reads_main_player(self):
        search = (
            '<a href="/video/abc-1234/">Wrong code</a>'
            '<a href="https://elsewhere.test/video/abc-123/">Wrong domain</a>'
            '<a href="/video/abc-123-sub/">Expected</a>'
        )
        detail = (
            '<meta property="og:title" content="ABC-123 Example">'
            '<div id="video-player"><div><video>'
            '<source src="//cdn.test/video.m3u8?a=1&amp;b=2">'
            '</video></div></div>'
            '<div data-mediabook="https://cdn.test/preview.mp4"></div>'
        )
        self.downloader._fetch_html = Mock(side_effect=[search, detail])
        info = self.downloader.parseHTML(self.downloader.getHTML("ABC-123"))
        self.assertEqual(info.avid, "ABC-123")
        self.assertEqual(info.m3u8, "https://cdn.test/video.m3u8?a=1&b=2")
        self.assertEqual(self.downloader._fetch_html.call_args.args[0],
                         "https://www.javhdporn.net/video/abc-123-sub/")

    def test_related_preview_is_not_a_media_source(self):
        self.downloader._page_url = "https://www.javhdporn.net/video/abc-123/"
        detail = ('<div id="video-player"><div></div></div>'
                  '<video src="https://cdn.test/preview.mp4"></video>')
        self.assertIsNone(self.downloader.parseHTML(detail))

    def test_fc2_page_title_uses_spaces_instead_of_hyphens(self):
        self.downloader._fetch_html = Mock(side_effect=[
            '<a href="/video/fc2-ppv-4613381/">Expected</a>',
            '<meta property="og:title" content="FC2 PPV 4613381 Example">'
            '<div id="video-player"><video src="https://cdn.test/movie.mp4"></video></div>',
        ])
        html = self.downloader.getHTML("FC2-PPV-4613381")
        info = self.downloader.parseHTML(html)
        self.assertEqual(info.avid, "FC2-PPV-4613381")
        self.assertEqual(info.title, "Example")

    def test_dynamic_player_reads_browser_source(self):
        self.downloader._page_url = "https://www.javhdporn.net/video/abc-123/"
        self.downloader._avid = "ABC-123"
        self.downloader._play_in_browser = Mock(return_value="https://cdn.test/movie.mp4")
        detail = ('<meta property="og:title" content="ABC-123 Example">'
                  '<div id="video-player" data-mpu="opaque"></div>')
        self.assertEqual(self.downloader.parseHTML(detail).m3u8, "https://cdn.test/movie.mp4")
        self.downloader._play_in_browser.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
