"""CLI behavior without contacting download sites or writing media files."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class NoFanArtFlagTest(unittest.TestCase):
    def run_main(self, *options, duplicate_source=False, torrent_downloaded=False):
        downloader = Mock()
        downloader.setDomain.return_value = True
        downloader.getDownloaderName.return_value = "MissAV"
        downloader.downloadInfo.return_value = types.SimpleNamespace(m3u8="https://example.com/video.m3u8")
        downloader.downloadM3u8.return_value = not duplicate_source

        source = types.ModuleType("src")
        manager = types.ModuleType("src.downloaderMgr")
        manager.DownloaderMgr = Mock(return_value=types.SimpleNamespace(GetDownloader=Mock(return_value=downloader)))
        source.downloaderMgr = manager
        data = types.ModuleType("src.data")
        data.initialize_db = Mock()
        data.find_in_db = Mock(return_value=False)
        source.data = data
        metadata = types.ModuleType("metadata")
        metadata.gen_nfo = Mock()
        metadata.rebuild_fanart = Mock(return_value=[])
        metadata.VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts"}
        sukebei = types.ModuleType("src.downloader.sukebei")
        sukebei.download_from_sukebei = Mock(return_value=torrent_downloaded)

        with tempfile.TemporaryDirectory() as directory:
            comm = types.ModuleType("src.comm")
            comm.os = os
            comm.logger = Mock()
            comm.downloaded_path = str(Path(directory) / "downloaded.db")
            comm.save_path = str(Path(directory) / "videos")
            comm.queue_path = str(Path(directory) / "queue.txt")
            comm.sorted_downloaders = [{"downloaderName": "MissAV", "domain": "example.com"}]
            if duplicate_source:
                comm.sorted_downloaders.append({"downloaderName": "MissAV", "domain": "example.net"})
            modules = {
                "src": source,
                "src.comm": comm,
                "src.data": data,
                "src.downloaderMgr": manager,
                "src.downloader.sukebei": sukebei,
                "metadata": metadata,
            }
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                Path("work").write_text("0", encoding="utf-8")
                with patch.dict(sys.modules, modules), patch.object(
                    sys, "argv", ["main.py", *([] if "--rebuild-fanart" in options else ["TEST-123"]), *options]
                ):
                    if "--rebuild-fanart" in options or torrent_downloaded:
                        with self.assertRaises(SystemExit) as stopped:
                            runpy.run_path(str(MAIN), run_name="__main__")
                        self.assertEqual(stopped.exception.code, 0)
                    else:
                        runpy.run_path(str(MAIN), run_name="__main__")
                if duplicate_source:
                    if torrent_downloaded:
                        self.assertFalse(Path(comm.queue_path).exists())
                    else:
                        self.assertEqual(Path(comm.queue_path).read_text(encoding="utf-8"), "TEST-123\n")
                    self.assertEqual(downloader.downloadInfo.call_count, 2)
                    sukebei.download_from_sukebei.assert_called_once_with("TEST-123", Path(comm.save_path) / "TEST-123")
                else:
                    sukebei.download_from_sukebei.assert_not_called()
            finally:
                os.chdir(old_cwd)

        if "--rebuild-fanart" in options:
            downloader.downloadM3u8.assert_not_called()
            data.initialize_db.assert_not_called()
            metadata.rebuild_fanart.assert_called_once_with(None)
        else:
            downloader.downloadM3u8.assert_called_once()
        return metadata.gen_nfo

    def test_default_generates_nfo(self):
        self.run_main().assert_called_once_with("TEST-123")

    def test_no_fan_art_skips_nfo(self):
        self.run_main("--no-fan-art").assert_not_called()

    def test_rebuild_fanart_never_downloads_video(self):
        self.run_main("--rebuild-fanart").assert_not_called()

    def test_same_failed_hls_source_is_not_downloaded_twice(self):
        self.run_main(duplicate_source=True).assert_not_called()

    def test_torrent_success_skips_queue_and_fanart(self):
        self.run_main(duplicate_source=True, torrent_downloaded=True).assert_not_called()


if __name__ == "__main__":
    unittest.main()
