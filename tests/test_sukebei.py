"""Torrent selection must only list matching releases and never auto-select."""

import importlib
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class SukebeiFallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cffi = types.ModuleType("curl_cffi")
        cffi.requests = types.SimpleNamespace()
        with patch.dict(sys.modules, {"curl_cffi": cffi}):
            cls.module = importlib.import_module("src.downloader.sukebei")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.sukebei", None)

    def test_feed_matches_exact_code_and_trusted_download_host(self):
        feed = b"""
        <rss xmlns:nyaa="https://sukebei.nyaa.si/xmlns/nyaa"><channel>
          <item><title>FC2-PPV-11828760 Different</title>
            <link>https://sukebei.nyaa.si/download/1.torrent</link></item>
          <item><title>FC2-PPV-1182876 External</title>
            <link>https://example.test/download/2.torrent</link></item>
          <item><title>FC2 PPV 1182876 First</title>
            <link>https://sukebei.nyaa.si/download/3.torrent</link>
            <nyaa:seeders>2</nyaa:seeders><nyaa:size>2 GiB</nyaa:size></item>
          <item><title>FC2PPV-1182876 Second</title>
            <link>https://sukebei.nyaa.si/download/4.torrent</link>
            <nyaa:seeders>5</nyaa:seeders></item>
        </channel></rss>
        """
        choices = self.module._parse_feed(feed, "FC2-PPV-1182876")
        self.assertEqual([(item.torrent_id, item.seeders) for item in choices], [("4", 5), ("3", 2)])

    def test_cancel_does_not_start_download(self):
        torrent = self.module.Torrent("1", "FC2-PPV-1182876", "2 GiB", 0)
        with patch.object(self.module.sys.stdin, "isatty", return_value=True), \
             patch.object(self.module.sys.stdout, "isatty", return_value=True), \
             patch.object(self.module, "_search", return_value=[torrent]), \
             patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess([], 130)), \
             patch.object(self.module, "_download") as download:
            self.assertFalse(self.module.download_from_sukebei("FC2-PPV-1182876", Path("/unused")))
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
