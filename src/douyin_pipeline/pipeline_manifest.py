from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.downloader import DownloadResult
from douyin_pipeline.errors import UserFacingError
from douyin_pipeline.jobs import relative_to, write_manifest
from douyin_pipeline.parser import detect_source_platform
from douyin_pipeline.transcriber import TranscriptResult


def build_manifest(
    *,
    settings: Settings,
    prepared_job,
    status: str,
    detail: str,
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
) -> dict[str, Any]:
    video_path = download_result.video_path if download_result else None
    audio_path = resolve_audio_path(download_result, transcript_result)
    transcript_path = resolve_transcript_path(download_result, transcript_result)
    transcript_text = (
        transcript_result.text
        if transcript_result
        else load_transcript_preview(prepared_job.job_dir)
    )

    return {
        "job_id": prepared_job.job_dir.name,
        "job_dir": prepared_job.job_dir.name,
        "created_at": prepared_job.created_at,
        "action": prepared_job.action,
        "status": status,
        "detail": detail,
        "raw_input": prepared_job.raw_input,
        "source_url": prepared_job.source_url,
        "source_platform": detect_source_platform(prepared_job.source_url),
        "title": download_result.title if download_result else None,
        "video_path": relative_to(settings.output_dir, video_path),
        "audio_path": relative_to(settings.output_dir, audio_path),
        "transcript_path": relative_to(settings.output_dir, transcript_path),
        "transcript_preview": truncate_text(transcript_text),
        **build_error_fields(error=error, error_info=error_info),
        "phase": phase,
        "progress_percent": progress_percent,
        "eta_seconds": eta_seconds,
        "processed_seconds": processed_seconds,
        "duration_seconds": duration_seconds,
    }


def merge_existing_manifest(
    manifest: dict[str, Any],
    *,
    settings: Settings,
    status: str,
    detail: str,
    transcript_result: Optional[TranscriptResult],
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
) -> dict[str, Any]:
    updated = dict(manifest)
    updated["status"] = status
    updated["detail"] = detail
    updated.update(build_error_fields(error=error, error_info=error_info))
    updated["phase"] = phase
    updated["progress_percent"] = progress_percent
    updated["eta_seconds"] = eta_seconds
    updated["processed_seconds"] = processed_seconds
    updated["duration_seconds"] = duration_seconds

    if transcript_result:
        updated["audio_path"] = relative_to(settings.output_dir, transcript_result.audio_path)
        updated["transcript_path"] = relative_to(settings.output_dir, transcript_result.transcript_path)
        updated["transcript_preview"] = truncate_text(transcript_result.text)
    else:
        audio_rel = updated.get("audio_path")
        transcript_rel = updated.get("transcript_path")
        if not transcript_rel:
            updated["transcript_preview"] = ""

        if audio_rel:
            audio_path = settings.output_dir / str(audio_rel)
            if not audio_path.exists():
                updated["audio_path"] = None

        if transcript_rel:
            transcript_path = settings.output_dir / str(transcript_rel)
            if transcript_path.exists():
                updated["transcript_preview"] = truncate_text(
                    transcript_path.read_text(encoding="utf-8")
                )
            else:
                updated["transcript_path"] = None
                updated["transcript_preview"] = ""

    return updated


def build_error_fields(
    *,
    error: Optional[str],
    error_info: Optional[UserFacingError],
) -> dict[str, Optional[str]]:
    if error_info is None:
        return {
            "error": error,
            "error_code": None,
            "error_kind": None,
            "error_hint": None,
            "technical_error": None,
        }

    return {
        "error": error_info.message,
        "error_code": error_info.code,
        "error_kind": error_info.kind,
        "error_hint": error_info.hint,
        "technical_error": error_info.technical_detail,
    }


def resolve_audio_path(
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
) -> Optional[Path]:
    if transcript_result:
        return transcript_result.audio_path

    if not download_result:
        return None

    candidate = download_result.video_path.with_suffix(".wav")
    return candidate if candidate.exists() else None


def resolve_transcript_path(
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
) -> Optional[Path]:
    if transcript_result:
        return transcript_result.transcript_path

    if not download_result:
        return None

    candidate = download_result.video_path.with_suffix(".txt")
    return candidate if candidate.exists() else None


def load_transcript_preview(job_dir: Path) -> str:
    transcript_files = sorted(job_dir.glob("*.txt"))
    if not transcript_files:
        return ""
    return transcript_files[0].read_text(encoding="utf-8")


def truncate_text(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def infer_processed_seconds(transcript_result: Optional[TranscriptResult]) -> Optional[float]:
    if transcript_result is None:
        return None
    return transcript_result.duration_seconds


def write_manifest_with_callback(
    job_dir: Path,
    payload: dict[str, Any],
    status_callback,
) -> None:
    write_manifest(job_dir, payload)
    if status_callback is not None:
        status_callback(dict(payload))
