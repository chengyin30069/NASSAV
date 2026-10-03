"""Provider routing and artwork output regression tests."""

from io import BytesIO
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from PIL import Image


def picture(size):
    output = BytesIO()
    Image.new("RGB", size, "blue").save(output, format="JPEG")
    return output.getvalue()


def reply(*, payload=None, body=b"", html="", content_type="text/html"):
    return types.SimpleNamespace(
        json=lambda: payload,
        content=body,
        text=html,
        headers={"Content-Type": content_type},
        raise_for_status=lambda: None,
    )


class ArtworkScraperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_cffi = types.ModuleType("curl_cffi")
        fake_cffi.requests = types.SimpleNamespace(
            get=Mock(), exceptions=types.SimpleNamespace(RequestException=Exception)
        )
        fake_comm = types.ModuleType("src.comm")
        fake_comm.configs = {"Fanart": {"MaxPreviewImages": 3}}
        with patch.dict(sys.modules, {"curl_cffi": fake_cffi, "src.comm": fake_comm}):
            cls.module = importlib.import_module("src.scraper")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("src.scraper", None)

    def test_fc2_number_routing(self):
        for avid in ("FC2-PPV-4826883", "fc2-4826883", "FC2PPV4826883"):
            self.assertEqual(self.module.fc2_number(avid), "4826883")
        self.assertIsNone(self.module.fc2_number("MIGD-649"))

    def test_fc2_official_images_and_nfo(self):
        with tempfile.TemporaryDirectory() as directory:
            scraper = self.module.ArtworkScraper(directory)
            folder = Path(directory, "FC2-PPV-4826883")
            folder.mkdir()
            (folder / "FC2-PPV-4826883.nfo").write_text(
                "<movie><title>Original title</title><plot>Keep this plot</plot>"
                "<art><fanart>missing.jpg</fanart></art></movie>", encoding="utf-8"
            )
            html = (
                '<meta property="og:title" content="FC2-PPV-4826883 Example">'
                '<meta property="og:image" content="https://images.example/cover.jpg">'
                '<a data-pdp-sample-thumbnail href="//images.example/sample.jpg">image</a>'
            )
            urls = []

            def get(url):
                urls.append(url)
                if "/article/" in url:
                    return reply(html=html)
                return reply(body=picture((700, 500)), content_type="image/jpeg")

            with patch.object(scraper, "_get", side_effect=get):
                result = scraper.scrape("FC2-PPV-4826883", preserve_existing_nfo=True)
            self.assertEqual(result.source, "FC2 Content Market")
            self.assertEqual(len(urls), 3)
            self.assertTrue((folder / "FC2-PPV-4826883-poster.jpg").is_file())
            root = ET.parse(folder / "FC2-PPV-4826883.nfo").getroot()
            self.assertEqual(root.findtext("title"), "Original title")
            self.assertEqual(root.findtext("plot"), "Keep this plot")
            art = root.findall("art/fanart")
            self.assertEqual([item.text for item in art], [
                "FC2-PPV-4826883-fanart-1.jpg", "FC2-PPV-4826883-fanart-2.jpg"
            ])

    def test_regular_stops_at_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            scraper = self.module.ArtworkScraper(directory)
            payload = {
                "content_id": "migd00649", "title": "Example",
                "images": {"jacket_image": {"large2": "https://images.example/cover.jpg"}},
                "release_date": "2015-05-13", "runtime_minutes": 152,
            }
            urls = []

            def get(url):
                urls.append(url)
                if "r18.dev" in url:
                    return reply(payload=payload)
                size = (90, 122) if "jp-2.jpg" in url else (700, 500)
                return reply(body=picture(size), content_type="image/jpeg")

            with patch.object(scraper, "_get", side_effect=get):
                result = scraper.scrape("MIGD-649")
            self.assertEqual(result.source, "R18/FANZA")
            self.assertEqual(len(urls), 4)
            folder = Path(directory, "MIGD-649")
            self.assertFalse((folder / "MIGD-649-fanart-3.jpg").exists())
            art = ET.parse(folder / "MIGD-649.nfo").getroot().findall("art/fanart")
            self.assertEqual(len(art), 2)

    def test_fc2_fallback_does_not_accept_wrong_id(self):
        with tempfile.TemporaryDirectory() as directory:
            scraper = self.module.ArtworkScraper(directory)
            page = '<script data-page="app" type="application/json">' + json.dumps({
                "props": {"article": {"video_id": 999, "image_url": "https://images.example/cover.jpg"}}
            }) + "</script>"

            def get(url):
                return reply(html=page if "fc2cmadb" in url else "<title>Missing</title>")

            with patch.object(scraper, "_get", side_effect=get):
                self.assertIsNone(scraper.scrape("FC2-PPV-4826883"))
            self.assertFalse(Path(directory, "FC2-PPV-4826883").exists())


if __name__ == "__main__":
    unittest.main()
