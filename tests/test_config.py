from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from douyin_pipeline.config import _discover_ytdlp_command


class ConfigTests(unittest.TestCase):
    def test_discover_ytdlp_prefers_standalone_binary_candidates(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            standalone = home / ".local" / "bin" / "yt-dlp"
            standalone.parent.mkdir(parents=True)
            standalone.write_bytes(b"binary")

            with patch("douyin_pipeline.config.Path.home", return_value=home), patch(
                "douyin_pipeline.config.shutil.which",
                return_value="C:/old-yt-dlp.exe",
            ), patch(
                "douyin_pipeline.config._venv_script",
                return_value=None,
            ), patch(
                "douyin_pipeline.config.importlib.util.find_spec",
                return_value=None,
            ):
                actual = _discover_ytdlp_command()

        self.assertEqual(actual, str(standalone))


if __name__ == "__main__":
    unittest.main()
