"""Batch repair selects video folders missing fanart and leaves complete folders alone."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class RebuildFanartTest(unittest.TestCase):
    def test_batch_selection_and_explicit_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("MIGD-649", "FC2-PPV-4826883", "EMPTY", "thumb"):
                (root / name).mkdir()
            (root / "MIGD-649" / "MIGD-649.mp4").write_bytes(b"video")
            (root / "FC2-PPV-4826883" / "video.mkv").write_bytes(b"video")
            (root / "FC2-PPV-4826883" / "FC2-PPV-4826883-fanart-1.jpg").write_bytes(b"art")

            scraper = Mock()

            def scrape(name, preserve_existing_nfo=False):
                self.assertTrue(preserve_existing_nfo)
                (root / name / f"{name}-fanart-1.jpg").write_bytes(b"art")
                return object()

            scraper.scrape.side_effect = scrape
            fake_comm = types.ModuleType("src.comm")
            fake_comm.save_path = directory
            fake_comm.myproxy = None
            fake_comm.logger = Mock()
            fake_scraper = types.ModuleType("src.scraper")
            fake_scraper.ArtworkScraper = Mock(return_value=scraper)
            fake_data = types.ModuleType("src.data")
            with patch.dict(sys.modules, {"src.comm": fake_comm, "src.scraper": fake_scraper, "src.data": fake_data}):
                module = importlib.import_module("metadata")
                try:
                    self.assertEqual(module.rebuild_fanart(), [])
                    scraper.scrape.assert_called_once_with("MIGD-649", preserve_existing_nfo=True)
                    scraper.scrape.reset_mock()
                    self.assertEqual(module.rebuild_fanart("FC2-PPV-4826883"), [])
                    scraper.scrape.assert_called_once_with("FC2-PPV-4826883", preserve_existing_nfo=True)
                finally:
                    sys.modules.pop("metadata", None)


if __name__ == "__main__":
    unittest.main()
