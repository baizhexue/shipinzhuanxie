from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import write_manifest
from douyin_pipeline.web_jobs import (
    can_transcribe_manifest,
    delete_job_payload,
    get_job_transcript_payload,
    list_jobs_payload,
    prepare_job_creation,
    queue_existing_transcribe,
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
    )


def _write_job(output_dir: Path, job_id: str, **overrides) -> Path:
    job_dir = output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(
        job_dir,
        {
            "job_id": job_id,
            "job_dir": job_id,
            "created_at": "2026-03-20T12:00:00",
            "action": "download",
            "status": "success",
            "detail": "completed",
            "raw_input": "https://example.com/video",
            "source_url": "https://example.com/video",
            "title": "demo",
            "video_path": "job/demo.mp4",
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
            **overrides,
        },
    )
    return job_dir


class WebJobsTests(unittest.TestCase):
    def test_list_jobs_payload_clamps_limit_and_returns_public_jobs(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            _write_job(settings.output_dir, "job-1")
            _write_job(settings.output_dir, "job-2", status="error", detail="failed")

            payload = list_jobs_payload(settings, limit=999)

        self.assertEqual(payload["limit"], 50)
        self.assertEqual(payload["filtered_total"], 2)
        self.assertEqual(len(payload["jobs"]), 2)
        self.assertEqual(payload["summary"]["total"], 2)

    def test_get_job_transcript_payload_returns_text_and_count(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            job_dir = _write_job(
                settings.output_dir,
                "job-1",
                transcript_path="job-1/demo.txt",
                transcript_preview="hello",
            )
            (job_dir / "demo.txt").write_text("hello world", encoding="utf-8")

            payload = get_job_transcript_payload(settings, "job-1")

        assert payload is not None
        self.assertEqual(payload["transcript_text"], "hello world")
        self.assertEqual(payload["transcript_char_count"], 11)

    def test_queue_existing_transcribe_updates_manifest_state(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            _write_job(settings.output_dir, "job-1")

            payload = queue_existing_transcribe(settings, "job-1")

        assert payload is not None
        self.assertEqual(payload["status"], "transcribing")
        self.assertEqual(payload["phase"], "extracting_audio")
        self.assertEqual(payload["progress_percent"], 34.0)

    def test_can_transcribe_manifest_checks_status_video_and_transcript(self) -> None:
        self.assertTrue(
            can_transcribe_manifest(
                {
                    "status": "success",
                    "video_path": "demo.mp4",
                    "transcript_path": None,
                }
            )
        )
        self.assertFalse(
            can_transcribe_manifest(
                {
                    "status": "transcribing",
                    "video_path": "demo.mp4",
                    "transcript_path": None,
                }
            )
        )
        self.assertFalse(
            can_transcribe_manifest(
                {
                    "status": "success",
                    "video_path": None,
                    "transcript_path": None,
                }
            )
        )

    def test_prepare_job_creation_delegates_to_pipeline_prepare_job(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            sentinel = object()

            with patch("douyin_pipeline.web_jobs.prepare_job", return_value=sentinel) as mocked_prepare:
                actual = prepare_job_creation(
                    settings,
                    raw_input="https://example.com/video",
                    action="run",
                )

        self.assertIs(actual, sentinel)
        mocked_prepare.assert_called_once_with("https://example.com/video", settings, "run")

    def test_delete_job_payload_returns_deleted_public_job(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            _write_job(settings.output_dir, "job-1")

            payload = delete_job_payload(settings, "job-1")

        self.assertEqual(payload["deleted_job"]["job_id"], "job-1")
        self.assertEqual(payload["message"], "任务已删除。")


if __name__ == "__main__":
    unittest.main()
