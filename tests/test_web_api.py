from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import STALE_TIMEOUT_SECONDS, read_manifest, write_manifest
from douyin_pipeline.web import create_app


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


class FakeTelegramManager:
    def __init__(self) -> None:
        self.saved_payloads: list[dict] = []
        self.state = {
            "config": {
                "enabled": False,
                "has_token": False,
                "token_masked": "",
                "allowed_chat_ids": [],
                "allowed_chat_ids_text": "",
                "public_base_url": "http://127.0.0.1:8000",
                "poll_timeout": 15,
                "retry_delay": 3.0,
                "progress_updates": True,
            },
            "runtime": {
                "running": False,
                "bot_username": None,
                "last_error": None,
                "mode": "managed_by_web",
            },
        }

    def get_public_state(self) -> dict:
        return self.state

    def save_config(self, payload: dict) -> dict:
        self.saved_payloads.append(dict(payload))
        token = str(payload.get("token") or "").strip()
        if payload.get("clear_token"):
            token = ""
        self.state = {
            "config": {
                "enabled": bool(payload.get("enabled", self.state["config"]["enabled"])),
                "has_token": bool(token or self.state["config"]["has_token"]),
                "token_masked": "123456...abcd" if (token or self.state["config"]["has_token"]) else "",
                "allowed_chat_ids": [5515267321],
                "allowed_chat_ids_text": str(payload.get("allowed_chat_ids", "5515267321")),
                "public_base_url": str(
                    payload.get("public_base_url", self.state["config"]["public_base_url"])
                ),
                "poll_timeout": int(payload.get("poll_timeout", 15)),
                "retry_delay": float(payload.get("retry_delay", 3.0)),
                "progress_updates": bool(payload.get("progress_updates", True)),
            },
            "runtime": {
                "running": bool(payload.get("enabled", self.state["runtime"]["running"])),
                "bot_username": "demo_bot" if payload.get("enabled") else None,
                "last_error": None,
                "mode": "managed_by_web",
            },
        }
        return self.state


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        DummyThread.instances = []

    def test_create_job_without_input_returns_structured_error(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            response = client.post("/api/jobs", json={"raw_input": "", "action": "download"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error_code"], "invalid_input")
        self.assertTrue(payload["error_hint"])

    def test_create_job_returns_queued_manifest(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))

            def fake_prepare_job(raw_input: str, request_settings: Settings, action: str):
                job_dir = request_settings.output_dir / "job-test"
                job_dir.mkdir(parents=True, exist_ok=True)
                write_manifest(
                    job_dir,
                    {
                        "job_id": "job-test",
                        "job_dir": "job-test",
                        "created_at": "2026-03-09T10:00:00",
                        "action": action,
                        "status": "queued",
                        "detail": "Job queued.",
                        "raw_input": raw_input,
                        "source_url": "https://v.douyin.com/test/",
                        "title": None,
                        "video_path": None,
                        "audio_path": None,
                        "transcript_path": None,
                        "transcript_preview": None,
                        "error": None,
                        "error_code": None,
                        "error_kind": None,
                        "error_hint": None,
                        "technical_error": None,
                        "phase": "queued",
                        "progress_percent": 0.0,
                        "eta_seconds": None,
                        "processed_seconds": 0.0,
                        "duration_seconds": None,
                    },
                )
                return SimpleNamespace(job_dir=job_dir)

            with patch("douyin_pipeline.web.prepare_job", side_effect=fake_prepare_job), patch(
                "douyin_pipeline.web.Thread",
                DummyThread,
            ), TestClient(create_app(settings)) as client:
                response = client.post(
                    "/api/jobs",
                    json={
                        "raw_input": "https://v.douyin.com/test/",
                        "action": "download",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["job_id"], "job-test")
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertTrue(DummyThread.instances[0].started)

    def test_jobs_endpoint_supports_summary_and_pagination(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            output_dir = Path(tmp_dir)
            for index, status in enumerate(["success", "error"], start=1):
                job_dir = output_dir / f"job-{index}"
                job_dir.mkdir(parents=True, exist_ok=True)
                write_manifest(
                    job_dir,
                    {
                        "job_id": f"job-{index}",
                        "job_dir": f"job-{index}",
                        "created_at": f"2026-03-09T10:00:0{index}",
                        "action": "download",
                        "status": status,
                        "detail": status,
                        "raw_input": f"https://v.douyin.com/test-{index}/",
                        "source_url": f"https://v.douyin.com/test-{index}/",
                        "title": f"demo-{index}",
                        "video_path": None,
                        "audio_path": None,
                        "transcript_path": None,
                        "transcript_preview": None,
                        "error": None,
                        "error_code": None,
                        "error_kind": None,
                        "error_hint": None,
                        "technical_error": None,
                        "phase": "completed" if status == "success" else "failed",
                        "progress_percent": 100.0,
                        "eta_seconds": 0.0,
                        "processed_seconds": 1.0,
                        "duration_seconds": 1.0,
                    },
                )

            response = client.get("/api/jobs?limit=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["jobs"]), 1)
        self.assertEqual(payload["filtered_total"], 2)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["error"], 1)

    def test_jobs_endpoint_marks_stale_active_job_as_error(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            job_dir = Path(tmp_dir) / "job-stale"
            job_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = write_manifest(
                job_dir,
                {
                    "job_id": "job-stale",
                    "job_dir": "job-stale",
                    "created_at": "2026-03-12T14:50:25",
                    "action": "run",
                    "status": "downloading",
                    "detail": "Downloading...",
                    "raw_input": "https://v.douyin.com/demo/",
                    "source_url": "https://v.douyin.com/demo/",
                    "source_platform": "douyin",
                    "title": "demo",
                    "video_path": None,
                    "audio_path": None,
                    "transcript_path": None,
                    "transcript_preview": None,
                    "error": None,
                    "error_code": None,
                    "error_kind": None,
                    "error_hint": None,
                    "technical_error": None,
                    "phase": "downloading",
                    "progress_percent": 8.0,
                    "eta_seconds": None,
                    "processed_seconds": 0.0,
                    "duration_seconds": None,
                },
            )
            expired_at = time.time() - STALE_TIMEOUT_SECONDS["downloading"] - 30
            os.utime(manifest_path, (expired_at, expired_at))
            client.app.state.last_stale_sweep_monotonic = 0.0

            response = client.get("/api/jobs")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["jobs"][0]["job_id"], "job-stale")
        self.assertEqual(payload["jobs"][0]["status"], "error")
        self.assertEqual(payload["jobs"][0]["error_code"], "stale_job_timeout")
        self.assertTrue(payload["jobs"][0]["status_note"])

    def test_delete_job_removes_completed_history_item(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            job_dir = Path(tmp_dir) / "job-delete"
            job_dir.mkdir(parents=True, exist_ok=True)
            write_manifest(
                job_dir,
                {
                    "job_id": "job-delete",
                    "job_dir": "job-delete",
                    "created_at": "2026-03-09T10:00:00",
                    "action": "download",
                    "status": "success",
                    "detail": "done",
                    "raw_input": "https://v.douyin.com/test/",
                    "source_url": "https://v.douyin.com/test/",
                    "title": "demo",
                    "video_path": None,
                    "audio_path": None,
                    "transcript_path": None,
                    "transcript_preview": None,
                    "error": None,
                    "error_code": None,
                    "error_kind": None,
                    "error_hint": None,
                    "technical_error": None,
                    "phase": "completed",
                    "progress_percent": 100.0,
                    "eta_seconds": 0.0,
                    "processed_seconds": 1.0,
                    "duration_seconds": 1.0,
                },
            )

            response = client.delete("/api/jobs/job-delete")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_job"]["job_id"], "job-delete")
        self.assertFalse(job_dir.exists())

    def test_transcribe_endpoint_updates_manifest_before_background_run(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            job_dir = settings.output_dir / "job-1"
            job_dir.mkdir(parents=True, exist_ok=True)
            video_path = job_dir / "video.mp4"
            video_path.write_bytes(b"video")
            write_manifest(
                job_dir,
                {
                    "job_id": "job-1",
                    "job_dir": "job-1",
                    "created_at": "2026-03-09T10:00:00",
                    "action": "download",
                    "status": "success",
                    "detail": "Job completed.",
                    "raw_input": "https://v.douyin.com/test/",
                    "source_url": "https://v.douyin.com/test/",
                    "title": "demo",
                    "video_path": "job-1/video.mp4",
                    "audio_path": None,
                    "transcript_path": None,
                    "transcript_preview": None,
                    "error": None,
                    "error_code": None,
                    "error_kind": None,
                    "error_hint": None,
                    "technical_error": None,
                    "phase": "completed",
                    "progress_percent": 100.0,
                    "eta_seconds": 0.0,
                    "processed_seconds": 1.0,
                    "duration_seconds": 1.0,
                },
            )

            with patch("douyin_pipeline.web.Thread", DummyThread), TestClient(create_app(settings)) as client:
                response = client.post("/api/jobs/job-1/transcribe", json={})

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "transcribing")
            self.assertEqual(payload["phase"], "extracting_audio")
            refreshed = read_manifest(job_dir)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed["status"], "transcribing")
            self.assertEqual(len(DummyThread.instances), 1)
            self.assertTrue(DummyThread.instances[0].started)

    def test_telegram_settings_require_token_when_enabled(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            client.app.state.telegram_manager = FakeTelegramManager()
            response = client.put(
                "/api/settings/telegram",
                json={
                    "enabled": True,
                    "token": "",
                    "allowed_chat_ids": "5515267321",
                },
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error_code"], "telegram_token_missing")

    def test_telegram_start_uses_web_managed_config(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            fake_manager = FakeTelegramManager()
            client.app.state.telegram_manager = fake_manager

            response = client.post(
                "/api/settings/telegram/start",
                json={
                    "token": "123456:demo-token",
                    "allowed_chat_ids": "5515267321",
                    "public_base_url": "http://127.0.0.1:8000",
                    "progress_updates": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["config"]["enabled"])
        self.assertTrue(payload["runtime"]["running"])
        self.assertEqual(fake_manager.saved_payloads[0]["enabled"], True)

    def test_job_transcript_endpoint_returns_full_text(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(create_app(_make_settings(Path(tmp_dir)))) as client:
            job_dir = Path(tmp_dir) / "job-transcript"
            job_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = job_dir / "demo.txt"
            transcript_path.write_text("完整转写文本", encoding="utf-8")
            write_manifest(
                job_dir,
                {
                    "job_id": "job-transcript",
                    "job_dir": "job-transcript",
                    "created_at": "2026-03-12T10:00:00",
                    "action": "run",
                    "status": "success",
                    "detail": "done",
                    "raw_input": "https://youtu.be/demo",
                    "source_url": "https://youtu.be/demo",
                    "source_platform": "youtube",
                    "title": "demo",
                    "video_path": None,
                    "audio_path": None,
                    "transcript_path": "job-transcript/demo.txt",
                    "transcript_preview": "完整转写文本",
                    "error": None,
                    "error_code": None,
                    "error_kind": None,
                    "error_hint": None,
                    "technical_error": None,
                    "phase": "completed",
                    "progress_percent": 100.0,
                    "eta_seconds": 0.0,
                    "processed_seconds": 1.0,
                    "duration_seconds": 1.0,
                },
            )

            response = client.get("/api/jobs/job-transcript/transcript")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["transcript_text"], "完整转写文本")
        self.assertEqual(payload["transcript_char_count"], len("完整转写文本"))

    def test_openclaw_health_requires_token_when_configured(self) -> None:
        with TemporaryDirectory() as tmp_dir, TestClient(
            create_app(replace(_make_settings(Path(tmp_dir)), openclaw_token="demo-token"))
        ) as client:
            response = client.get("/api/openclaw/health")

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["error_code"], "openclaw_auth_invalid")

    def test_openclaw_transcribe_returns_full_transcript(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = replace(_make_settings(Path(tmp_dir)), openclaw_token="demo-token")
            job_dir = settings.output_dir / "job-openclaw"
            job_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = job_dir / "demo.txt"
            transcript_path.write_text("这里是完整稿子", encoding="utf-8")

            manifest = {
                "job_id": "job-openclaw",
                "job_dir": "job-openclaw",
                "created_at": "2026-03-12T10:00:00",
                "action": "run",
                "status": "success",
                "detail": "done",
                "raw_input": "https://youtu.be/demo",
                "source_url": "https://youtu.be/demo",
                "source_platform": "youtube",
                "title": "demo",
                "video_path": None,
                "audio_path": None,
                "transcript_path": "job-openclaw/demo.txt",
                "transcript_preview": "这里是完整稿子",
                "error": None,
                "error_code": None,
                "error_kind": None,
                "error_hint": None,
                "technical_error": None,
                "phase": "completed",
                "progress_percent": 100.0,
                "eta_seconds": 0.0,
                "processed_seconds": 1.0,
                "duration_seconds": 1.0,
            }

            with patch("douyin_pipeline.web.process_job", return_value=manifest) as mocked_process, TestClient(
                create_app(settings)
            ) as client:
                response = client.post(
                    "/api/openclaw/transcribe",
                    headers={"X-OpenClaw-Token": "demo-token"},
                    json={"raw_input": "https://youtu.be/demo"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_id"], "job-openclaw")
        self.assertEqual(payload["source_platform"], "youtube")
        self.assertEqual(payload["transcript_text"], "这里是完整稿子")
        mocked_process.assert_called_once()


if __name__ == "__main__":
    unittest.main()
