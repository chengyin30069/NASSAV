"""Rapidgator link selection, authorized resolution, and ranged file download."""

import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, Mock, patch


class _Response:
    def __init__(self, data=None, status=200, headers=None, chunks=()):
        self.data = data
        self.status_code = status
        self.headers = headers or {}
        self.chunks = chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _RequestError()

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        return iter(self.chunks)

    def close(self):
        pass


class _RequestError(Exception):
    pass


class RapidgatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_cffi = types.ModuleType("curl_cffi")
        fake_cffi.requests = types.SimpleNamespace(
            Session=Mock(), exceptions=types.SimpleNamespace(RequestException=_RequestError)
        )
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            cls.module = importlib.import_module("src.downloader.rapidgator")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.rapidgator", None)

    def test_only_file_link_is_selected(self):
        page = ("<a href='magnet:?xt=urn:btih:abc'>Magnet</a>"
                "<a href='https://evil.test/file/123456789abcdef0'>Other</a>"
                "<a href='https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda'>Download</a>")
        self.assertEqual(self.module.extract_rapidgator_link(page),
                         "https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda")

    def test_native_api_resolves_filename_and_direct_link(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = [
            _Response({"response": {"token": "secret-token"}}),
            _Response({"response": {"file": {"name": "movie.mp4", "size": 6}}}),
            _Response({"response": {"download_url": "https://files.test/movie.mp4"}}),
        ]
        with patch.object(self.module.requests, "Session", return_value=session), \
             patch.dict(os.environ, {"RAPIDGATOR_LOGIN": "user", "RAPIDGATOR_PASSWORD": "secret"}):
            result = self.module._resolve_native(
                "https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda",
                10, None, "chrome120",
            )
        self.assertEqual(result, ("https://files.test/movie.mp4", "movie.mp4", 6))
        self.assertEqual(session.get.call_count, 3)

    def test_range_resume_writes_only_missing_bytes(self):
        file_id = "72816cb5fb1e1f8cbf88958782795dda"
        public_url = f"https://rapidgator.net/file/{file_id}"
        response = _Response(status=206, headers={"Content-Range": "bytes 3-5/6",
                                                  "Content-Type": "video/mp4"}, chunks=(b"def",))
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, f".TEST-1.{file_id}.mp4.part").write_bytes(b"abc")
            with patch.object(self.module, "configured_backend", return_value="rapidgator"), \
                 patch.object(self.module, "_resolve_native", return_value=("https://files.test/movie.mp4", "movie.mp4", 6)), \
                 patch.object(self.module.requests, "Session", return_value=session):
                target = self.module.download_rapidgator(public_url, directory, "TEST-1")
            self.assertEqual(target.read_bytes(), b"abcdef")
            self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=3-")
            self.assertFalse(Path(directory, f".TEST-1.{file_id}.mp4.part").exists())

    def test_portal_waits_until_file_is_ready(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = _Response({"success": True, "data": {
            "linkId": "abc123", "download_ready": False, "poll_after_seconds": 2,
        }})
        session.get.return_value = _Response({"success": True, "data": {
            "download_ready": True, "link": "https://files.test/movie.mp4",
            "filename": "movie.mp4", "filesize": "6",
        }})
        with patch.object(self.module.requests, "Session", return_value=session), \
             patch.object(self.module.time, "sleep") as sleep, \
             patch.dict(os.environ, {"STORAGE_PORTAL_API_KEY": "secret"}):
            result = self.module._resolve_portal(
                "https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda",
                10, None, "chrome120",
            )
        self.assertEqual(result, ("https://files.test/movie.mp4", "movie.mp4", "6"))
        sleep.assert_called_once_with(2.0)
        self.assertTrue(session.get.call_args.args[0].endswith("/link/abc123"))

    def test_rejects_archive_before_downloading(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.module, "configured_backend", return_value="rapidgator"), \
             patch.object(self.module, "_resolve_native", return_value=("https://files.test/movie.rar", "movie.rar", 6)):
            with self.assertRaisesRegex(ValueError, "not a supported video"):
                self.module.download_rapidgator("https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda",
                                                directory, "TEST-1")

    def test_manual_direct_url_requires_matching_public_file_id(self):
        settings = {
            "RAPIDGATOR_DIRECT_URL": "https://files.test/movie.mp4",
            "RAPIDGATOR_DIRECT_FILENAME": "movie.mp4",
            "RAPIDGATOR_DIRECT_FILE_ID": "another-file-id",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, settings):
            with self.assertRaisesRegex(ValueError, "different file ID"):
                self.module.download_rapidgator(
                    "https://rapidgator.net/file/72816cb5fb1e1f8cbf88958782795dda",
                    directory, "TEST-1",
                )


if __name__ == "__main__":
    unittest.main()
