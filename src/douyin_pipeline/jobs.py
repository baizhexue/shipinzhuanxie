from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional


MANIFEST_NAME = "manifest.json"
ACTIVE_STATUSES = {"queued", "downloading", "transcribing", "running"}
STALE_TIMEOUT_SECONDS = {
    "queued": 180,
    "downloading": 480,
    "running": 1800,
    "transcribing": 1800,
}


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
    payload["status_note"] = _build_status_note(payload)
    return payload


def read_transcript_text(output_dir: Path, manifest: dict[str, Any]) -> Optional[str]:
    transcript_rel = manifest.get("transcript_path")
    if not transcript_rel:
        return None

    transcript_path = output_dir / str(transcript_rel)
    if not transcript_path.exists():
        return None

    return transcript_path.read_text(encoding="utf-8")


def sweep_stale_jobs(output_dir: Path) -> int:
    if not output_dir.exists():
        return 0

    updated_count = 0
    now = time.time()

    for job_dir in output_dir.iterdir():
        if not job_dir.is_dir() or not job_dir.name.startswith("job-"):
            continue

        manifest_path = job_dir / MANIFEST_NAME
        if not manifest_path.exists():
            continue

        manifest = read_manifest(job_dir)
        if manifest is None:
            continue

        status = str(manifest.get("status") or "")
        timeout_seconds = STALE_TIMEOUT_SECONDS.get(status)
        if timeout_seconds is None:
            continue

        age_seconds = now - manifest_path.stat().st_mtime
        if age_seconds < timeout_seconds:
            continue

        manifest.update(
            {
                "status": "error",
                "phase": "failed",
                "detail": "任务长时间无进展，系统已自动终止。",
                "error": "任务长时间无进展，系统已自动终止。",
                "error_code": "stale_job_timeout",
                "error_kind": "runtime",
                "error_hint": "可以直接重试；如果是抖音下载，系统会在超时后自动回退浏览器解析。",
                "technical_error": (
                    f"Job stayed in `{status}` for {int(age_seconds)} seconds "
                    "without manifest updates."
                ),
                "progress_percent": None,
                "eta_seconds": None,
            }
        )
        write_manifest(job_dir, manifest)
        updated_count += 1

    return updated_count


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


def _build_status_note(manifest: dict[str, Any]) -> Optional[str]:
    error_code = str(manifest.get("error_code") or "")
    status = str(manifest.get("status") or "")
    platform = str(manifest.get("source_platform") or "")

    if error_code == "download_timeout":
        return "下载器长时间无响应，任务已自动停止。重新发起后会再次尝试，并对抖音触发浏览器回退。"
    if error_code == "stale_job_timeout":
        return "任务长时间没有进展，系统已自动标记失败，避免一直挂在历史记录里。"
    if status == "queued":
        return "任务已进入后台队列，通常会在几秒内开始处理。"
    if status == "downloading" and platform == "douyin":
        return "抖音会先尝试 yt-dlp；如果长时间无响应，会自动切到浏览器回退下载。"
    if status == "transcribing":
        return "转写阶段会持续刷新进度，首次加载模型时会比普通阶段更慢。"
    return None
