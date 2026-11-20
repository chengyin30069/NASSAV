"""HLS segment concurrency and failure handling."""

from contextlib import nullcontext
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import types
import unittest
from unittest.mock import Mock, patch


class _RequestError(Exception):
    pass


class MissAVHlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_cffi = types.ModuleType("curl_cffi")
        fake_cffi.requests = types.SimpleNamespace(
            get=Mock(), Session=Mock(), exceptions=types.SimpleNamespace(RequestException=_RequestError)
        )
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            cls.module = importlib.import_module("src.downloader.missavHls")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.missavHls", None)

    def test_four_workers_download_segments_in_parallel_and_preserve_playlist_order(self):
        barrier = Barrier(4, timeout=5)
        playlist_url = "https://cdn.test/list.m3u8"
        playlist = b"#EXTM3U\n" + b"".join(
            f"#EXTINF:1,\n{index}.ts\n".encode() for index in range(8)
        )

        def fetch(url, *_args, **_kwargs):
            if url == playlist_url:
                return types.SimpleNamespace(url=playlist_url, content=playlist)
            number = int(Path(url).stem)
            if number < 4:
                barrier.wait()
            return str(number).encode()

        def remux(args, **_kwargs):
            local_playlist = Path(args[args.index("-i") + 1])
            names = [line for line in local_playlist.read_text().splitlines() if not line.startswith("#")]
            self.assertEqual(
                [(local_playlist.parent / name).read_bytes() for name in names],
                [str(number).encode() for number in range(8)],
            )
            Path(args[-1]).write_bytes(b"mp4")
            return types.SimpleNamespace(returncode=0, stderr="")

        with TemporaryDirectory() as directory, \
             patch.object(self.module.requests, "Session", side_effect=lambda: nullcontext(object())) as session, \
             patch.object(self.module, "_fetch", side_effect=fetch), \
             patch.object(self.module.subprocess, "run", side_effect=remux):
            video = Path(directory) / "video.mp4"
            self.module.download_media(playlist_url, video, {}, "chrome110")
            self.assertEqual(video.read_bytes(), b"mp4")
        self.assertEqual(session.call_count, 4)

    def test_transport_error_is_retried(self):
        response = types.SimpleNamespace(status_code=200, content=b"segment", raise_for_status=lambda: None)
        with patch.object(self.module.requests, "get", side_effect=[_RequestError("reset"), response]) as get:
            self.assertEqual(self.module._fetch("https://cdn.test/0.ts", {}, "chrome110", None, 10), b"segment")
        self.assertEqual(get.call_count, 2)

    def test_forbidden_segment_reports_stage_without_retry(self):
        with patch.object(self.module.requests, "get", return_value=types.SimpleNamespace(status_code=403)) as get:
            with self.assertRaisesRegex(RuntimeError, r"segment 3/5 denied \(HTTP 403, cdn.test\)"):
                self.module._fetch("https://cdn.test/0.ts?token=secret", {}, "chrome120", None, 10,
                                   stage="segment 3/5")
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
