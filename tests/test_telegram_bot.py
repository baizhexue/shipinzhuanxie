from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.deepseek_summary import SummaryResult
from douyin_pipeline.telegram_bot import (
    TelegramBotRunner,
    TelegramBotSettings,
    TelegramProgressReporter,
)


def _make_settings(output_dir: Path, *, deepseek_api_key: Optional[str] = None) -> Settings:
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
        deepseek_api_key=deepseek_api_key,
    )


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, Optional[dict]]] = []
        self.edits: list[tuple[int, int, str, Optional[dict]]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.documents: list[tuple[int, Path, Optional[str]]] = []
        self.callback_answers: list[tuple[str, Optional[str], bool]] = []
        self.cleared_markups: list[tuple[int, int]] = []

    def send_message(self, chat_id: int, text: str, *, reply_markup: Optional[dict] = None) -> dict:
        self.messages.append((chat_id, text, reply_markup))
        return {"ok": True, "message_id": 9001}

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: Optional[dict] = None,
    ) -> dict:
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True, "message_id": message_id}

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

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> dict:
        self.callback_answers.append((callback_query_id, text, show_alert))
        return {"ok": True}

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        *,
        reply_markup: Optional[dict] = None,
    ) -> dict:
        self.cleared_markups.append((chat_id, message_id))
        return {"ok": True}

    def delete_message(self, chat_id: int, message_id: int) -> dict:
        self.deleted_messages.append((chat_id, message_id))
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
                    public_base_url="http://127.0.0.1:4444",
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
                    public_base_url="http://127.0.0.1:4444",
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._handle_update({"message": {"chat": {"id": 1001}, "text": "/web"}})
            self.assertEqual(client.messages, [(1001, "http://127.0.0.1:4444", None)])

    def test_valid_link_sends_mode_selection(self) -> None:
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
            self.assertIn("请选择这条任务的处理方式", client.messages[0][1])
            self.assertIsNotNone(client.messages[0][2])
            self.assertEqual(len(DummyThread.instances), 0)
            self.assertEqual(len(runner._state["pending_requests"]), 1)

    def test_download_mode_starts_immediately_without_summary_step(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir), deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._state["pending_requests"] = {
                "req-1": {"chat_id": 1001, "raw_input": "https://v.douyin.com/test/", "created_at": 1.0}
            }
            with patch("douyin_pipeline.telegram_bot.Thread", DummyThread):
                runner._handle_update(
                    {
                        "callback_query": {
                            "id": "cb-1",
                            "data": "txmode:download:req-1",
                            "from": {"id": 1001},
                            "message": {"message_id": 5001, "chat": {"id": 1001}},
                        }
                    }
                )

            self.assertEqual(client.callback_answers, [("cb-1", "已选择只下载视频", False)])
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertEqual(DummyThread.instances[0].args, (1001, "https://v.douyin.com/test/", "download", None))

    def test_summary_selection_is_front_loaded_after_run_mode(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir), deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._state["pending_requests"] = {
                "req-1": {"chat_id": 1001, "raw_input": "https://v.douyin.com/test/", "created_at": 1.0}
            }
            with patch("douyin_pipeline.telegram_bot.Thread", DummyThread):
                runner._handle_update(
                    {
                        "callback_query": {
                            "id": "cb-1",
                            "data": "txmode:accurate:req-1",
                            "from": {"id": 1001},
                            "message": {"message_id": 5001, "chat": {"id": 1001}},
                        }
                    }
                )

            self.assertEqual(client.callback_answers, [("cb-1", "已选择高精度转写", False)])
            self.assertEqual(len(DummyThread.instances), 0)
            self.assertIn("自动总结", client.messages[-1][1])
            self.assertIsNotNone(client.messages[-1][2])
            self.assertEqual(len(runner._state["pending_summaries"]), 1)

    def test_summary_callback_starts_job_with_selected_summary_style(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir), deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._state["pending_summaries"] = {
                "sum-1": {
                    "chat_id": 1001,
                    "raw_input": "https://v.douyin.com/test/",
                    "mode": "accurate",
                    "created_at": 1.0,
                }
            }
            with patch("douyin_pipeline.telegram_bot.Thread", DummyThread):
                runner._handle_update(
                    {
                        "callback_query": {
                            "id": "cb-2",
                            "data": "txsummary:plain:sum-1",
                            "from": {"id": 1001},
                            "message": {"message_id": 5002, "chat": {"id": 1001}},
                        }
                    }
                )

            self.assertEqual(client.callback_answers, [("cb-2", "已选择大白话总结", False)])
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertEqual(
                DummyThread.instances[0].args,
                (1001, "https://v.douyin.com/test/", "accurate", "plain"),
            )

    def test_summary_callback_can_skip_summary_and_still_start_job(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(Path(tmp_dir), deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=Path(tmp_dir) / "state.json",
                ),
                client,
            )
            runner._state["pending_summaries"] = {
                "sum-1": {
                    "chat_id": 1001,
                    "raw_input": "https://v.douyin.com/test/",
                    "mode": "fast",
                    "created_at": 1.0,
                }
            }
            with patch("douyin_pipeline.telegram_bot.Thread", DummyThread):
                runner._handle_update(
                    {
                        "callback_query": {
                            "id": "cb-3",
                            "data": "txsummary:skip:sum-1",
                            "from": {"id": 1001},
                            "message": {"message_id": 5003, "chat": {"id": 1001}},
                        }
                    }
                )

            self.assertEqual(client.callback_answers, [("cb-3", "已跳过总结，将直接开始任务。", False)])
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertEqual(
                DummyThread.instances[0].args,
                (1001, "https://v.douyin.com/test/", "fast", None),
            )

    def test_process_message_job_includes_summary_label_when_selected(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            job_dir = output_dir / "job-1"
            job_dir.mkdir(parents=True)
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(output_dir, deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=output_dir / "state.json",
                ),
                client,
            )

            with patch("douyin_pipeline.telegram_bot.prepare_job") as prepare_job, patch(
                "douyin_pipeline.telegram_bot.run_prepared_job"
            ) as run_prepared_job, patch(
                "douyin_pipeline.telegram_bot.TelegramProgressReporter"
            ) as progress_reporter_cls:
                prepared_job = type("Prepared", (), {"job_dir": job_dir, "action": "run"})()
                prepare_job.return_value = prepared_job
                run_prepared_job.return_value = {"job_id": "job-1", "status": "success"}
                with patch.object(runner, "_send_success") as send_success, patch.object(
                    runner, "_process_summary_job"
                ) as process_summary_job:
                    runner._process_message_job(1001, "https://v.douyin.com/test/", "fast", "knowledge")

            self.assertIn("总结：知识型", client.messages[0][1])
            self.assertEqual(progress_reporter_cls.call_args.kwargs["progress_message_id"], 9001)
            progress_reporter_cls.return_value.dismiss.assert_called_once()
            send_success.assert_called_once()
            process_summary_job.assert_called_once_with(1001, "job-1", "knowledge")

    def test_send_success_no_longer_prompts_for_summary(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            job_dir = output_dir / "job-1"
            job_dir.mkdir(parents=True)
            transcript_path = job_dir / "demo.txt"
            transcript_path.write_text("hello world", encoding="utf-8")
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(output_dir, deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=output_dir / "state.json",
                ),
                client,
            )

            runner._send_success(
                1001,
                {
                    "job_id": "job-1",
                    "status": "success",
                    "title": "demo",
                    "transcript_path": "job-1/demo.txt",
                    "transcript_preview": "hello world",
                },
            )

            self.assertEqual(len(client.documents), 1)
            self.assertEqual(len(runner._state["pending_summaries"]), 0)
            self.assertNotIn("自动总结", client.messages[-1][1])

    def test_process_summary_job_sends_title_and_document(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            job_dir = output_dir / "job-1"
            job_dir.mkdir(parents=True)
            summary_path = job_dir / "OpenClaw 技能接入说明-通用总结.md"
            client = FakeTelegramClient()
            runner = TelegramBotRunner(
                _make_settings(output_dir, deepseek_api_key="secret"),
                TelegramBotSettings(
                    token="token",
                    allowed_chat_ids=(1001,),
                    public_base_url=None,
                    state_path=output_dir / "state.json",
                ),
                client,
            )

            with patch("douyin_pipeline.telegram_bot.read_manifest", return_value={"job_id": "job-1"}), patch(
                "douyin_pipeline.telegram_bot.read_transcript_text",
                return_value="原文",
            ), patch(
                "douyin_pipeline.telegram_bot.summarize_to_file",
                return_value=SummaryResult(
                    style="general",
                    label="通用",
                    title="OpenClaw 技能接入说明",
                    text="## 概述\n\n这是总结正文。",
                    markdown="# OpenClaw 技能接入说明\n\n## 概述\n\n这是总结正文。",
                    summary_path=summary_path,
                ),
            ):
                runner._process_summary_job(1001, "job-1", "general")

            self.assertIn("已开始总结", client.messages[0][1])
            self.assertIn("标题：OpenClaw 技能接入说明", client.messages[1][1])
            self.assertIn("## 概述", client.messages[2][1])
            self.assertEqual(client.documents[-1], (1001, summary_path, "通用总结 - OpenClaw 技能接入说明"))

    def test_progress_reporter_sends_phase_and_progress_updates(self) -> None:
        client = FakeTelegramClient()
        reporter = TelegramProgressReporter(client, 1001, enabled=True, progress_message_id=9001)
        reporter.handle_manifest({"job_id": "job-1", "status": "downloading", "phase": "downloading"})

        reporter._last_phase = "transcribing"
        reporter._last_progress_percent = 60.0
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
        reporter.dismiss()

        self.assertEqual(client.messages, [])
        self.assertEqual(len(client.edits), 2)
        self.assertIn("job-1", client.edits[0][2])
        self.assertIn("68%", client.edits[1][2])
        self.assertEqual(client.deleted_messages, [(1001, 9001)])


if __name__ == "__main__":
    unittest.main()
