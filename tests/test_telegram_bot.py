from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.telegram_bot import (
    TelegramBotRunner,
    TelegramBotSettings,
    TelegramProgressReporter,
)


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
        whisper_language=None,
        whisper_beam_size=5,
    )


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, Optional[dict]]] = []
        self.documents: list[tuple[int, Path, Optional[str]]] = []
        self.callback_answers: list[tuple[str, Optional[str], bool]] = []
        self.cleared_markups: list[tuple[int, int]] = []

    def send_message(self, chat_id: int, text: str, *, reply_markup: Optional[dict] = None) -> dict:
        self.messages.append((chat_id, text, reply_markup))
        return {"ok": True, "message_id": 9001}

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

    def answer_callback_query(self, callback_query_id: str, *, text: Optional[str] = None, show_alert: bool = False) -> dict:
        self.callback_answers.append((callback_query_id, text, show_alert))
        return {"ok": True}

    def edit_message_reply_markup(self, chat_id: int, message_id: int, *, reply_markup: Optional[dict] = None) -> dict:
        self.cleared_markups.append((chat_id, message_id))
        return {"ok": True}


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
            self.assertEqual(client.messages, [(1001, "http://127.0.0.1:8000", None)])

    def test_valid_link_sends_mode_selection_instead_of_starting_job_immediately(self) -> None:
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

            self.assertEqual(len(client.messages), 1)
            chat_id, text, reply_markup = client.messages[0]
            self.assertEqual(chat_id, 1001)
            self.assertIn("请选择这条任务的处理方式", text)
            self.assertIsNotNone(reply_markup)
            self.assertEqual(len(DummyThread.instances), 0)
            self.assertEqual(len(runner._state["pending_requests"]), 1)

    def test_callback_query_starts_background_job_with_selected_mode(self) -> None:
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
            runner._state["pending_requests"] = {
                "req-1": {
                    "chat_id": 1001,
                    "raw_input": "https://v.douyin.com/test/",
                    "created_at": 1.0,
                }
            }
            with patch("douyin_pipeline.telegram_bot.Thread", DummyThread):
                runner._handle_update(
                    {
                        "callback_query": {
                            "id": "cb-1",
                            "data": "txmode:accurate:req-1",
                            "from": {"id": 1001},
                            "message": {
                                "message_id": 5001,
                                "chat": {"id": 1001},
                            },
                        }
                    }
                )

            self.assertEqual(len(DummyThread.instances), 1)
            self.assertTrue(DummyThread.instances[0].started)
            self.assertEqual(DummyThread.instances[0].args, (1001, "https://v.douyin.com/test/", "accurate"))
            self.assertEqual(client.callback_answers, [("cb-1", "已选择高精度转写", False)])
            self.assertEqual(client.cleared_markups, [(1001, 5001)])
            self.assertEqual(runner._state["pending_requests"], {})

    def test_expired_callback_query_returns_expired_message(self) -> None:
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

            runner._handle_update(
                {
                    "callback_query": {
                        "id": "cb-1",
                        "data": "txmode:fast:req-missing",
                        "from": {"id": 1001},
                        "message": {
                            "message_id": 5001,
                            "chat": {"id": 1001},
                        },
                    }
                }
            )

            self.assertEqual(client.callback_answers, [("cb-1", "这个选择已经失效了，请重新发送一次链接。", False)])

    def test_progress_reporter_sends_phase_and_progress_updates(self) -> None:
        client = FakeTelegramClient()
        reporter = TelegramProgressReporter(client, 1001, enabled=True)
        reporter.handle_manifest(
            {
                "job_id": "job-1",
                "status": "downloading",
                "phase": "downloading",
            }
        )

        reporter._last_phase = "transcribing"
        reporter._last_bucket = 1
        reporter._last_sent_at = -999.0
        reporter.handle_manifest(
            {
                "job_id": "job-1",
                "status": "transcribing",
                "phase": "transcribing",
                "progress_percent": 68.0,
                "processed_seconds": 42.0,
                "duration_seconds": 120.0,
                "eta_seconds": 18.0,
            }
        )

        self.assertEqual(len(client.messages), 2)
        self.assertIn("job-1", client.messages[0][1])
        self.assertIn("68%", client.messages[1][1])


if __name__ == "__main__":
    unittest.main()
