"""MissAV HLS retries and segments share the same request pace."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class _RequestError(Exception):
    pass


class MissAVHlsPacingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_cffi = types.ModuleType("curl_cffi")
        fake_cffi.requests = types.SimpleNamespace(
            get=Mock(), exceptions=types.SimpleNamespace(RequestException=_RequestError)
        )
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi}):
            cls.module = importlib.import_module("src.downloader.missavHls")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.downloader.missavHls", None)

    def test_requests_are_spaced_even_after_403(self):
        clock = [0.0]
        starts = []
        attempts = [0]

        def get(*_args, **_kwargs):
            starts.append(clock[0])
            attempts[0] += 1
            if attempts[0] == 2:
                raise _RequestError("HTTP 403")
            return types.SimpleNamespace(content=b"segment", raise_for_status=lambda: None)

        def sleep(seconds):
            clock[0] += seconds

        pacer = self.module._RequestPacer(4.0)
        with patch.object(self.module.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(self.module.time, "sleep", side_effect=sleep), \
             patch.object(self.module.requests, "get", side_effect=get):
            self.module._fetch("https://cdn.test/0.ts", {}, "chrome120", None, 10, pacer=pacer)
            self.module._fetch("https://cdn.test/1.ts", {}, "chrome120", None, 10, pacer=pacer)

        self.assertEqual(starts, [0.0, 4.0, 8.0])

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module._RequestPacer(-1)


if __name__ == "__main__":
    unittest.main()
