from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import json
import shutil


MANIFEST_NAME = "manifest.json"
ACTIVE_STATUSES = {"queued", "downloading", "transcribing", "running"}


def write_manifest(job_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = job_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def read_manifest(job_dir: Path) -> Optional[dict[str, Any]]:
    manifest_path = job_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def list_job_manifests(
    output_dir: Path,
    *,
    offset: int = 0,
    limit: int = 20,
    q: str = "",
    status: Optional[str] = None,
    action: Optional[str] = None,
    active_only: bool = False,
) -> dict[str, Any]:
    manifests = _all_manifests(output_dir)
    summary = _build_summary(manifests)
    filtered = [
        manifest
        for manifest in manifests
        if _matches_filters(
            manifest,
            q=q,
            status=status,
            action=action,
            active_only=active_only,
        )
    ]

    safe_offset = max(offset, 0)
    safe_limit = max(limit, 1)
    items = filtered[safe_offset : safe_offset + safe_limit]

    return {
        "items": items,
        "offset": safe_offset,
        "limit": safe_limit,
        "filtered_total": len(filtered),
        "total_jobs": len(manifests),
        "has_more": safe_offset + safe_limit < len(filtered),
        "summary": summary,
    }


def delete_job(output_dir: Path, job_id: str) -> dict[str, Any]:
    job_dir = output_dir / job_id
    if not job_dir.exists() or not job_dir.is_dir():
        raise ValueError("Job not found.")
    if not job_dir.name.startswith("job-"):
        raise ValueError("Only generated job folders can be deleted.")

    manifest = read_manifest(job_dir) or {"job_id": job_id}
    if manifest.get("status") in ACTIVE_STATUSES:
        raise ValueError("Running jobs cannot be deleted.")

    shutil.rmtree(job_dir)
    return manifest


def relative_to(base_dir: Path, target: Optional[Path]) -> Optional[str]:
    if target is None:
        return None
    return str(target.resolve().relative_to(base_dir.resolve()))


def to_public_job(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = dict(manifest)
    files = []

    for key, label, kind in (
        ("video_path", "Video", "video"),
        ("audio_path", "Audio", "audio"),
        ("transcript_path", "Transcript", "text"),
    ):
        relative_path = payload.get(key)
        if not relative_path:
            continue

        relative_url = str(relative_path).replace("\\", "/")
        files.append(
            {
                "label": label,
                "kind": kind,
                "name": Path(relative_path).name,
                "url": f"/output/{relative_url}",
            }
        )

    payload["files"] = files
    payload["can_transcribe"] = bool(
        payload.get("video_path")
        and not payload.get("transcript_path")
        and payload.get("status") not in ACTIVE_STATUSES
    )
    payload["can_delete"] = payload.get("status") not in ACTIVE_STATUSES
    return payload


def read_transcript_text(output_dir: Path, manifest: dict[str, Any]) -> Optional[str]:
    transcript_rel = manifest.get("transcript_path")
    if not transcript_rel:
        return None

    transcript_path = output_dir / str(transcript_rel)
    if not transcript_path.exists():
        return None

    return transcript_path.read_text(encoding="utf-8")


def _all_manifests(output_dir: Path) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []

    manifests: list[dict[str, Any]] = []
    job_dirs = sorted(
        [path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("job-")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for job_dir in job_dirs:
        manifest = read_manifest(job_dir)
        if manifest is None:
            continue
        manifests.append(manifest)

    return manifests


def _matches_filters(
    manifest: dict[str, Any],
    *,
    q: str,
    status: Optional[str],
    action: Optional[str],
    active_only: bool,
) -> bool:
    manifest_status = str(manifest.get("status") or "")
    manifest_action = str(manifest.get("action") or "")

    if active_only and manifest_status not in ACTIVE_STATUSES:
        return False
    if status and manifest_status != status:
        return False
    if action and manifest_action != action:
        return False

    query = q.strip().lower()
    if not query:
        return True

    haystacks = [
        str(manifest.get("job_id") or ""),
        str(manifest.get("title") or ""),
        str(manifest.get("raw_input") or ""),
        str(manifest.get("source_url") or ""),
    ]
    return any(query in value.lower() for value in haystacks)


def _build_summary(manifests: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(manifests),
        "active": sum(1 for item in manifests if item.get("status") in ACTIVE_STATUSES),
        "success": sum(1 for item in manifests if item.get("status") == "success"),
        "error": sum(1 for item in manifests if item.get("status") == "error"),
        "download_only": sum(
            1
            for item in manifests
            if item.get("action") == "download" and not item.get("transcript_path")
        ),
        "with_transcript": sum(1 for item in manifests if item.get("transcript_path")),
    }
