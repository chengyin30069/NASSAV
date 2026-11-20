"""MissAV must skip its generic homepage when a variant URL is unavailable."""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


class MissAVPageSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = types.ModuleType("src.downloader.downloaderBase")
        base.Downloader = type("Downloader", (), {})
        base.AVDownloadInfo = type("AVDownloadInfo", (), {})
        base.logger = Mock()
        base.os = os
        base.requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=Exception))
        base.configs = {}
        base.project_root = "/NASSAV"
        hls = types.ModuleType("src.downloader.missavHls")
        hls.download_media = Mock()
        rapidgator = types.ModuleType("src.downloader.rapidgator")
        rapidgator.configured_backend = Mock(return_value=None)
        rapidgator.extract_rapidgator_link = Mock(return_value=None)
        rapidgator.download_rapidgator = Mock()
        with patch.dict(sys.modules, {"src.downloader.downloaderBase": base,
                                      "src.downloader.missavHls": hls,
                                      "src.downloader.rapidgator": rapidgator}):
            cls.module = importlib.import_module("src.downloader.missAVDownloader")
            cls.njav = importlib.import_module("src.downloader.njavDownloader")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.missAVDownloader", None)
        sys.modules.pop("src.downloader.njavDownloader", None)

    def test_skips_homepage_then_uses_matching_video(self):
        homepage = '<meta property="og:title" content="MissAV | 免费高清AV在线看">'
        video = (
            '<meta property="og:title" content="LOVE-122 Example">'
            '<script>m3u8|55c950ec6092|8265|400b|c4fc|2b696a73|com|surrit|https|video</script>'
        )
        downloader = self.module.MissAVDownloader()
        downloader.domain = "missav.ai"
        with patch.object(downloader, "_fetch_html", side_effect=[homepage, homepage, video], create=True) as fetch:
            self.assertEqual(downloader.getHTML("LOVE-122"), video)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args.args[0], "https://missav.ai/cn/love-122")

    def test_rejects_unrelated_video(self):
        unrelated = (
            '<meta property="og:title" content="LOVE-123 Example">'
            '<script>m3u8|55c950ec6092|8265|400b|c4fc|2b696a73|com|surrit|https|video</script>'
        )
        self.assertFalse(self.module.MissAVDownloader._is_target_video_page(unrelated, "LOVE-122"))

    def test_direct_file_path_does_not_require_hls_playlist(self):
        downloader = self.module.MissAVDownloader()
        page = '<meta property="og:title" content="LOVE-122 Example">'
        link = "https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda"
        with patch.object(self.module, "configured_backend", return_value="rapidgator"), \
             patch.object(self.module, "extract_rapidgator_link", return_value=link), \
             patch.object(downloader, "_get_highest_quality_m3u8", side_effect=AssertionError("HLS should not be fetched")):
            info = downloader.parseHTML(page)
        self.assertEqual(info.direct_url, link)

    def test_player_source_accepts_signed_playlist(self):
        page = (
            '<meta property="og:title" content="LOVE-122 Example">'
            '<source src="https://cdn.test/movie.m3u8?a=1&amp;b=2">'
        )
        downloader = self.module.MissAVDownloader()
        self.assertTrue(downloader._is_target_video_page(page, "LOVE-122"))
        self.assertEqual(downloader._extract_playlist_url(page), "https://cdn.test/movie.m3u8?a=1&b=2")

    def test_metadata_reads_fc2_code_with_reordered_attributes(self):
        page = """<meta content='fc2-ppv-4613381 A &amp; B' property='og:title'>"""
        metadata = self.module.AVDownloadInfo()
        self.assertTrue(self.module.MissAVDownloader._extract_metadata(page, metadata))
        self.assertEqual(metadata.avid, "FC2-PPV-4613381")
        self.assertEqual(metadata.title, "A & B")

    def test_master_uses_redirect_base_and_handles_attribute_order(self):
        downloader = self.module.MissAVDownloader()
        downloader.timeout = 10
        downloader.proxies = None
        response = Mock(
            status_code=200,
            url="https://cdn.test/redirected/master.m3u8",
            text='#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=640x360,BANDWIDTH=800\nlow.m3u8\n'
                 '#EXT-X-STREAM-INF:CODECS="avc1,mp4a",BANDWIDTH=1600\nhigh.m3u8\n',
        )
        with patch.object(downloader, "_media_headers", return_value={}), \
             patch.object(self.module.requests, "get", return_value=response, create=True):
            result = downloader._get_highest_quality_m3u8("https://cdn.test/master.m3u8")
        self.assertEqual(result, ("https://cdn.test/redirected/high.m3u8", ""))

    def test_njav_uses_video_page_and_its_own_media_referer(self):
        downloader = self.njav.NjavDownloader()
        downloader.domain = "njavtv.com"
        page = ('<meta property="og:title" content="FC2-PPV-4921544 Sample">'
                '<script>m3u8|3e02dc77c344|9c70|49eb|c47b|8cec98ac|com|surrit|https|video</script>')
        with patch.object(downloader, "_fetch_html", return_value=page, create=True) as fetch, \
             patch.object(downloader, "_get_highest_quality_m3u8",
                          return_value=("https://cdn.test/video.m3u8", "1280x720")) as playlist:
            info = downloader.parseHTML(downloader.getHTML("FC2-PPV-4921544"))
            self.assertIsNone(downloader.getHTML("FC2-PPV-492154"))
        fetch.assert_any_call("https://njavtv.com/en/fc2-ppv-4921544")
        playlist.assert_called_once_with(
            "https://surrit.com/8cec98ac-c47b-49eb-9c70-3e02dc77c344/playlist.m3u8"
        )
        self.assertEqual(info.avid, "FC2-PPV-4921544")
        self.assertEqual(downloader._media_headers(), {"Referer": "https://njavtv.com/"})


if __name__ == "__main__":
    unittest.main()
