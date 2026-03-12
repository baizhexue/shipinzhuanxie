from __future__ import annotations

from typing import Any

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import read_transcript_text, to_public_job


OPENCLAW_TOKEN_HEADER = "x-openclaw-token"
SUPPORTED_OPENCLAW_PLATFORMS = (
    "douyin",
    "bilibili",
    "xiaohongshu",
    "kuaishou",
    "youtube",
)


def validate_openclaw_token(settings: Settings, supplied_token: str | None) -> None:
    expected = (settings.openclaw_token or "").strip()
    if not expected:
        return

    if (supplied_token or "").strip() != expected:
        raise PermissionError("OpenClaw token is invalid.")


def build_openclaw_health_payload(settings: Settings) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "视频转写助手 OpenClaw 桥接",
        "supported_platforms": list(SUPPORTED_OPENCLAW_PLATFORMS),
        "requires_token": bool((settings.openclaw_token or "").strip()),
    }


def build_openclaw_transcript_payload(
    settings: Settings,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    transcript_text = read_transcript_text(settings.output_dir, manifest)
    if not transcript_text:
        raise ValueError("Transcript text was not produced.")

    public_job = to_public_job(manifest)
    return {
        "job": public_job,
        "job_id": str(public_job.get("job_id") or ""),
        "title": public_job.get("title"),
        "source_url": public_job.get("source_url"),
        "source_platform": public_job.get("source_platform"),
        "transcript_text": transcript_text,
        "transcript_char_count": len(transcript_text),
        "files": public_job.get("files", []),
    }
