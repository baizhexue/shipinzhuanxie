from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import read_manifest, write_manifest
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


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        DummyThread.instances = []

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
            ):
                client = TestClient(create_app(settings))
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
                    "phase": "completed",
                    "progress_percent": 100.0,
                    "eta_seconds": 0.0,
                    "processed_seconds": 1.0,
                    "duration_seconds": 1.0,
                },
            )

            with patch("douyin_pipeline.web.Thread", DummyThread):
                client = TestClient(create_app(settings))
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


if __name__ == "__main__":
    unittest.main()
