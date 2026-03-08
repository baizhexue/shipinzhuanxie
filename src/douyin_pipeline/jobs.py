from __future__ import annotations

from pathlib import Path
from typing import Any
import json
from typing import Optional


MANIFEST_NAME = "manifest.json"


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


def list_recent_manifests(output_dir: Path, limit: int = 8) -> list[dict[str, Any]]:
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
        if len(manifests) >= limit:
            break

    return manifests


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
        and payload.get("status") not in {"queued", "downloading", "transcribing", "running"}
    )
    return payload
