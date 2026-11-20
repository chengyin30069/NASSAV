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

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.missAVDownloader", None)

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


if __name__ == "__main__":
    unittest.main()
