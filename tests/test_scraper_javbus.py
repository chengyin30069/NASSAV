"""JavBus verification and cookie-scoping regression tests."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class JavBusRequestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_requests = types.SimpleNamespace(
            get=Mock(), exceptions=types.SimpleNamespace(RequestException=Exception)
        )
        fake_cffi = types.ModuleType("curl_cffi")
        fake_cffi.requests = fake_requests
        fake_comm = types.ModuleType("src.comm")
        fake_comm.configs = {}
        fake_comm.project_root = "/NASSAV"
        fake_comm.logger = Mock()
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi, "src.comm": fake_comm}):
            cls.scraper_module = importlib.import_module("src.scraper")
        cls.requests = fake_requests
        cls.comm = fake_comm

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.scraper", None)

    def setUp(self):
        self.requests.get.reset_mock()
        self.comm.logger.reset_mock()
        self.comm.configs.clear()

    def test_verification_redirect_is_not_parsed_as_video(self):
        self.requests.get.return_value = types.SimpleNamespace(
            status_code=302,
            headers={"Location": "/doc/driver-verify?referer=PIYO-217"},
            text="",
            raise_for_status=Mock(),
        )
        scraper = self.scraper_module.Sracper("/tmp")
        self.assertIsNone(scraper._fetch_html("https://www.javbus.com/PIYO-217"))
        self.assertIn("JavBus 要求", self.comm.logger.error.call_args.args[0])

    def test_cookie_only_goes_to_javbus(self):
        self.comm.configs["JavBus"] = {
            "Cookie": "age=verified; proof=valid",
            "UserAgent": "Browser UA",
        }
        scraper = self.scraper_module.Sracper("/tmp")
        first_party = scraper._request_headers("https://www.javbus.com/PIYO-217")
        third_party = scraper._request_headers("https://images.example/fanart.jpg")
        self.assertEqual(first_party["Cookie"], "age=verified; proof=valid")
        self.assertEqual(first_party["User-Agent"], "Browser UA")
        self.assertNotIn("Cookie", third_party)
        self.assertEqual(third_party["User-Agent"], "Browser UA")

    def test_cookie_file_is_loaded_for_javbus(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "javbus-cookie.txt").write_text(
                "proof=valid\nBrowser UA\n", encoding="utf-8"
            )
            self.comm.configs["JavBus"] = {
                "CookieFile": str(Path(directory, "javbus-cookie.txt"))
            }
            scraper = self.scraper_module.Sracper("/tmp")
            request_headers = scraper._request_headers("https://www.javbus.com/PIYO-217")
            self.assertEqual(request_headers["Cookie"], "proof=valid")
            self.assertEqual(request_headers["User-Agent"], "Browser UA")

    def test_age_verification_html_is_not_parsed_as_video(self):
        self.requests.get.return_value = types.SimpleNamespace(
            status_code=200,
            headers={},
            text="<title>Age Verification JavBus - JavBus</title>",
            raise_for_status=Mock(),
        )
        scraper = self.scraper_module.Sracper("/tmp")
        self.assertIsNone(scraper._fetch_html("https://www.javbus.com/PIYO-217"))
        self.assertIn("驗證頁", self.comm.logger.error.call_args.args[0])

    def test_redirected_image_is_not_saved(self):
        self.requests.get.return_value = types.SimpleNamespace(
            status_code=302,
            headers={"Location": "/doc/driver-verify"},
            raise_for_status=Mock(),
        )
        scraper = self.scraper_module.Sracper("/tmp")
        self.assertFalse(scraper._download_file("https://www.javbus.com/image.jpg", "image.jpg"))


if __name__ == "__main__":
    unittest.main()
