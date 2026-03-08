from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.telegram_bot import TelegramBotRunner, TelegramBotSettings


def _make_settings(output_dir: Path) -> Settings:
    return Settings(
        output_dir=output_dir,
        cookies_file=None,
        cookies_from_browser=None,
        ffmpeg_cmd=("ffmpeg",),
        ytdlp_cmd=("yt-dlp",),
        whisper_model="small",
        whisper_device="cpu",
    )


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, Path, Optional[str]]] = []

    def send_message(self, chat_id: int, text: str) -> dict:
        self.messages.append((chat_id, text))
        return {"ok": True}

    def send_document(
        self,
        chat_id: int,
        document_path: Path,
        *,
        caption: Optional[str] = None,
    ) -> dict:
        self.documents.append((chat_id, document_path, caption))
        return {"ok": True}

    def delete_webhook(self) -> None:
        return None

    def get_me(self) -> dict:
        return {"username": "test_bot"}

    def get_updates(self, *, offset, timeout, allowed_updates):
        return []


class DummyThread:
    instances = []

    def __init__(self, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        DummyThread.instances.append(self)

    def start(self) -> None:
        self.started = True


class TelegramBotTests(unittest.TestCase):
    def setUp(self) -> None:
        DummyThread.instances = []

    def test_unauthorized_chat_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir)),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url="http://127.0.0.1:8000",
                    state_path=Path(tmp_dir) / "state.json",
                ),
                FakeTelegramClient(),
            )
            runner._handle_update({"message": {"chat": {"id": 2002}, "text": "/start"}})
            self.assertEqual(runner._client.messages, [])

    def test_web_command_returns_public_url(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir)),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url="http://127.0.0.1:8000",
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._handle_update({"message": {"chat": {"id": 1001}, "text": "/web"}})
            self.assertEqual(client.messages, [(1001, "http://127.0.0.1:8000")])

    def test_valid_link_starts_background_job_thread(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir)),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            with patch("douyin_pipeline.telegram_bot.extract_share_url", return_value="https://v.douyin.com/test/"), patch(
                "douyin_pipeline.telegram_bot.Thread",
                DummyThread,
            ):
                runner._handle_update(
                    {"message": {"chat": {"id": 1001}, "text": "https://v.douyin.com/test/"}}
                )

            self.assertEqual(client.messages, [])
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertTrue(DummyThread.instances[0].started)


if __name__ == "__main__":
    unittest.main()
