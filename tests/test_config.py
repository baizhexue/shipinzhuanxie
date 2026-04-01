from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from douyin_pipeline.config import _discover_ytdlp_command, load_settings


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

    def test_load_settings_uses_balanced_whisper_defaults(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict("os.environ", {}, clear=True), patch(
            "douyin_pipeline.config._discover_ffmpeg_command",
            return_value="ffmpeg",
        ), patch(
            "douyin_pipeline.config._discover_ytdlp_command",
            return_value="yt-dlp",
        ):
            settings = load_settings(output_dir=tmp_dir)

        self.assertEqual(settings.whisper_model, "medium")
        self.assertEqual(settings.whisper_device, "auto")
        self.assertEqual(settings.whisper_beam_size, 5)
        self.assertIsNone(settings.whisper_language)

    def test_load_settings_normalizes_auto_language_to_none(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {"WHISPER_LANGUAGE": "auto", "WHISPER_BEAM_SIZE": "7"},
            clear=True,
        ), patch(
            "douyin_pipeline.config._discover_ffmpeg_command",
            return_value="ffmpeg",
        ), patch(
            "douyin_pipeline.config._discover_ytdlp_command",
            return_value="yt-dlp",
        ):
            settings = load_settings(output_dir=tmp_dir)

        self.assertIsNone(settings.whisper_language)
        self.assertEqual(settings.whisper_beam_size, 7)


if __name__ == "__main__":
    unittest.main()
