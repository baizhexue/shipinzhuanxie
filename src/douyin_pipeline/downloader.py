from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import subprocess
from typing import Optional

from douyin_pipeline.config import Settings


MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
}


@dataclass(frozen=True)
class DownloadResult:
    source_url: str
    title: str
    video_path: Path
    job_dir: Path


def create_job_dir(base_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    job_dir = base_dir / f"job-{stamp}"
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_dir


def download_video(
    source_url: str,
    settings: Settings,
    *,
    job_dir: Optional[Path] = None,
) -> DownloadResult:
    job_dir = job_dir or create_job_dir(settings.output_dir)
    try:
        return _download_with_ytdlp(source_url, settings, job_dir)
    except RuntimeError as exc:
        if _should_use_browser_fallback(source_url, exc):
            from douyin_pipeline.douyin_browser import download_with_browser

            return download_with_browser(source_url, job_dir)
        raise


def _download_with_ytdlp(
    source_url: str,
    settings: Settings,
    job_dir: Path,
) -> DownloadResult:
    output_template = str(job_dir / "%(title).80s_[%(id)s].%(ext)s")

    command = [
        *settings.ytdlp_cmd,
        "--no-playlist",
        "--restrict-filenames",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--print-json",
        "-o",
        output_template,
        source_url,
    ]

    if settings.cookies_from_browser:
        command.extend(["--cookies-from-browser", settings.cookies_from_browser])
    elif settings.cookies_file:
        command.extend(["--cookies", str(settings.cookies_file)])

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Video download failed.\n"
            f"command: {' '.join(command)}\n"
            f"stderr: {completed.stderr.strip()}"
        )

    title = _extract_title(completed.stdout)
    video_path = _find_downloaded_video(job_dir)

    return DownloadResult(
        source_url=source_url,
        title=title,
        video_path=video_path,
        job_dir=job_dir,
    )


def _should_use_browser_fallback(source_url: str, error: RuntimeError) -> bool:
    text = str(error)
    return (
        "douyin.com" in source_url
        and "Fresh cookies" in text
    )


def _extract_title(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
                title = payload.get("title")
                if title:
                    return str(title)
            except json.JSONDecodeError:
                continue

    return "untitled"


def _find_downloaded_video(job_dir: Path) -> Path:
    candidates = [
        path
        for path in job_dir.iterdir()
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    ]
    if not candidates:
        raise RuntimeError("Download command finished but no video file was found.")

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]
