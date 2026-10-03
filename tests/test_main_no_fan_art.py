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
    def run_main(self, *options):
        downloader = Mock()
        downloader.setDomain.return_value = True
        downloader.getDownloaderName.return_value = "MissAV"
        downloader.downloadInfo.return_value = types.SimpleNamespace(m3u8="https://example.com/video.m3u8")
        downloader.downloadM3u8.return_value = True

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

        with tempfile.TemporaryDirectory() as directory:
            comm = types.ModuleType("src.comm")
            comm.os = os
            comm.logger = Mock()
            comm.downloaded_path = str(Path(directory) / "downloaded.db")
            comm.save_path = str(Path(directory) / "videos")
            comm.queue_path = str(Path(directory) / "queue.txt")
            comm.sorted_downloaders = [{"downloaderName": "MissAV", "domain": "example.com"}]
            modules = {
                "src": source,
                "src.comm": comm,
                "src.data": data,
                "src.downloaderMgr": manager,
                "metadata": metadata,
            }
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                Path("work").write_text("0", encoding="utf-8")
                with patch.dict(sys.modules, modules), patch.object(
                    sys, "argv", ["main.py", *([] if "--rebuild-fanart" in options else ["TEST-123"]), *options]
                ):
                    if "--rebuild-fanart" in options:
                        with self.assertRaises(SystemExit) as stopped:
                            runpy.run_path(str(MAIN), run_name="__main__")
                        self.assertEqual(stopped.exception.code, 0)
                    else:
                        runpy.run_path(str(MAIN), run_name="__main__")
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


if __name__ == "__main__":
    unittest.main()
