from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import (
    ACTIVE_STATUSES,
    delete_job,
    list_job_manifests,
    read_manifest,
    read_transcript_text,
    to_public_job,
    write_manifest,
)
from douyin_pipeline.pipeline import prepare_job


def list_jobs_payload(
    settings: Settings,
    *,
    offset: int = 0,
    limit: int = 20,
    q: str = "",
    status: Optional[str] = None,
    action: Optional[str] = None,
    active_only: bool = False,
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 50))
    payload = list_job_manifests(
        settings.output_dir,
        offset=max(offset, 0),
        limit=safe_limit,
        q=q,
        status=status,
        action=action,
        active_only=active_only,
    )
    return {
        "jobs": [to_public_job(manifest) for manifest in payload["items"]],
        "offset": payload["offset"],
        "limit": payload["limit"],
        "filtered_total": payload["filtered_total"],
        "total_jobs": payload["total_jobs"],
        "has_more": payload["has_more"],
        "summary": payload["summary"],
    }


def get_public_job(settings: Settings, job_id: str) -> Optional[dict[str, Any]]:
    manifest = read_manifest(settings.output_dir / job_id)
    if manifest is None:
        return None
    return to_public_job(manifest)


def get_job_transcript_payload(settings: Settings, job_id: str) -> Optional[dict[str, Any]]:
    manifest = read_manifest(settings.output_dir / job_id)
    if manifest is None:
        return None
    transcript_text = read_transcript_text(settings.output_dir, manifest)
    return {
        "job": to_public_job(manifest),
        "transcript_text": transcript_text,
        "transcript_char_count": len(transcript_text) if transcript_text else 0,
    }


def prepare_job_creation(
    settings: Settings,
    *,
    raw_input: str,
    action: str,
) -> Any:
    return prepare_job(raw_input, settings, action)


def queue_existing_transcribe(settings: Settings, job_id: str) -> Optional[dict[str, Any]]:
    job_dir = settings.output_dir / job_id
    manifest = read_manifest(job_dir)
    if manifest is None:
        return None

    if manifest.get("transcript_path"):
        return to_public_job(manifest)

    queued_manifest = dict(manifest)
    queued_manifest.update(
        {
            "status": "transcribing",
            "detail": "Preparing transcript for existing video.",
            "phase": "extracting_audio",
            "progress_percent": 34.0,
            "eta_seconds": None,
            "processed_seconds": 0.0,
            "duration_seconds": None,
            "error": None,
            "error_code": None,
            "error_kind": None,
            "error_hint": None,
            "technical_error": None,
        }
    )
    write_manifest(job_dir, queued_manifest)

    refreshed = read_manifest(job_dir)
    return to_public_job(refreshed) if refreshed is not None else None


def get_job_manifest(settings: Settings, job_id: str) -> Optional[dict[str, Any]]:
    return read_manifest(settings.output_dir / job_id)


def can_transcribe_manifest(manifest: dict[str, Any]) -> bool:
    return (
        manifest.get("status") not in ACTIVE_STATUSES
        and bool(manifest.get("video_path"))
        and not manifest.get("transcript_path")
    )


def delete_job_payload(settings: Settings, job_id: str) -> dict[str, Any]:
    deleted = delete_job(settings.output_dir, job_id)
    return {
        "deleted_job": to_public_job(deleted),
        "message": "任务已删除。",
    }
