from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from douyin_pipeline.config import Settings
from douyin_pipeline.runtime_config import TelegramWebConfig, save_telegram_web_config
from douyin_pipeline.telegram_manager import TelegramManager


def _make_settings(output_dir: Path) -> Settings:
    return Settings(
        output_dir=output_dir,
        cookies_file=None,
        cookies_from_browser=None,
        ffmpeg_cmd=("ffmpeg",),
        ytdlp_cmd=("yt-dlp",),
        whisper_model="small",
        whisper_device="cpu",
        openclaw_token=None,
    )


class TelegramManagerTests(unittest.TestCase):
    def test_ensure_started_from_saved_does_not_raise_when_start_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            save_telegram_web_config(
                settings.output_dir,
                TelegramWebConfig(enabled=True, token="demo-token"),
            )
            manager = TelegramManager(settings)

            with patch.object(manager, "start", side_effect=RuntimeError("boom")):
                manager.ensure_started_from_saved()

            state = manager.get_public_state()
            self.assertEqual(state["runtime"]["last_error"], "boom")
            self.assertFalse(state["runtime"]["running"])
            self.assertTrue(state["config"]["enabled"])
            self.assertTrue(state["config"]["has_token"])


if __name__ == "__main__":
    unittest.main()
