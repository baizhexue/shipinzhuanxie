from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import json
import re
import shutil
import subprocess
from typing import Callable, Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.downloader_fallbacks import resolve_download_fallback
from douyin_pipeline.downloader_runtime import (
    build_ytdlp_process_env as _runtime_build_ytdlp_process_env,
    can_use_deno_compat_mode as _runtime_can_use_deno_compat_mode,
    detect_ytdlp_js_runtime as _runtime_detect_ytdlp_js_runtime,
    find_common_js_runtime_path as _runtime_find_common_js_runtime_path,
    ytdlp_supports_js_runtimes as _runtime_ytdlp_supports_js_runtimes,
)
from douyin_pipeline.parser import detect_source_platform
from douyin_pipeline.subprocess_utils import run_command


MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
}
AUDIO_SUFFIXES = {
    ".m4a",
    ".aac",
    ".mp3",
    ".opus",
    ".wav",
    ".flac",
}
ADAPTIVE_STREAM_PATTERN = re.compile(r"\.f\d+$")
YTDLP_DOWNLOAD_TIMEOUT_SECONDS = 180
YTDLP_HELP_TIMEOUT_SECONDS = 8
logger = logging.getLogger(__name__)

DownloadProgressCallback = Optional[Callable[[dict[str, object]], None]]


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
    progress_callback: DownloadProgressCallback = None,
) -> DownloadResult:
    job_dir = job_dir or create_job_dir(settings.output_dir)
    platform = detect_source_platform(source_url)
    logger.info("download attempt platform=%s source_url=%s job_id=%s", platform, source_url, job_dir.name)
    try:
        return _download_with_ytdlp(source_url, settings, job_dir)
    except RuntimeError as exc:
        fallback = resolve_download_fallback(source_url, exc)
        if fallback is not None:
            _emit_download_progress(
                progress_callback,
                phase="downloading",
                progress_percent=14.0,
                detail="yt-dlp 失败，正在切换浏览器回退下载。",
            )
            logger.warning(
                "download fallback triggered platform=%s job_id=%s reason=%s",
                platform,
                job_dir.name,
                exc,
            )
            return fallback(source_url, job_dir)
        logger.exception("download failed without fallback platform=%s job_id=%s", platform, job_dir.name)
        raise


def _download_with_ytdlp(
    source_url: str,
    settings: Settings,
    job_dir: Path,
) -> DownloadResult:
    platform = detect_source_platform(source_url)
    process_env = None
    output_template = str(job_dir / "%(title).80s_[%(id)s].%(ext)s")

    command = [
        *settings.ytdlp_cmd,
        "--no-playlist",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--print-json",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
    ]

    if platform == "youtube":
        js_runtime = _detect_ytdlp_js_runtime()
        if js_runtime:
            if _ytdlp_supports_js_runtimes(settings.ytdlp_cmd):
                command.extend(["--js-runtimes", js_runtime])
            elif _can_use_deno_compat_mode(js_runtime):
                process_env = _build_ytdlp_process_env(js_runtime)

    command.append(source_url)

    ffmpeg_location = _resolve_ffmpeg_location(settings)
    if ffmpeg_location:
        command.extend(["--ffmpeg-location", ffmpeg_location])

    if settings.cookies_from_browser:
        command.extend(["--cookies-from-browser", settings.cookies_from_browser])
    elif settings.cookies_file:
        command.extend(["--cookies", str(settings.cookies_file)])

    try:
        completed = run_command(
            command,
            timeout=YTDLP_DOWNLOAD_TIMEOUT_SECONDS,
            env=process_env,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("yt-dlp timed out platform=%s job_id=%s timeout=%ss", platform, job_dir.name, YTDLP_DOWNLOAD_TIMEOUT_SECONDS)
        raise RuntimeError(
            "Video download failed.\n"
            f"command: {' '.join(command)}\n"
            f"stderr: yt-dlp timed out after {YTDLP_DOWNLOAD_TIMEOUT_SECONDS} seconds"
        ) from exc

    if completed.returncode != 0:
        logger.warning("yt-dlp exited non-zero platform=%s job_id=%s returncode=%s", platform, job_dir.name, completed.returncode)
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

    merged_candidates = [
        path
        for path in candidates
        if not ADAPTIVE_STREAM_PATTERN.search(path.stem)
    ]
    if merged_candidates:
        merged_candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return merged_candidates[0]

    if _has_separate_audio_stream(job_dir):
        raise RuntimeError(
            "Adaptive streams were downloaded but not merged into a playable file. "
            "yt-dlp needs ffmpeg access to assemble Bilibili-style video and audio streams."
        )

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_ffmpeg_location(settings: Settings) -> Optional[str]:
    if not settings.ffmpeg_cmd:
        return None

    candidate = Path(settings.ffmpeg_cmd[0]).expanduser()
    if candidate.exists():
        return str(candidate)
    return None


def _has_separate_audio_stream(job_dir: Path) -> bool:
    return any(
        path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        for path in job_dir.iterdir()
    )


def _detect_ytdlp_js_runtime() -> Optional[str]:
    return _runtime_detect_ytdlp_js_runtime(which=shutil.which, home_factory=Path.home)


def _find_common_js_runtime_path(name: str) -> Optional[str]:
    return _runtime_find_common_js_runtime_path(name, home_factory=Path.home)


def _ytdlp_supports_js_runtimes(command: tuple[str, ...]) -> bool:
    return _runtime_ytdlp_supports_js_runtimes(
        command,
        timeout=YTDLP_HELP_TIMEOUT_SECONDS,
    )


def _can_use_deno_compat_mode(js_runtime: str) -> bool:
    return _runtime_can_use_deno_compat_mode(js_runtime)


def _build_ytdlp_process_env(js_runtime: str) -> Optional[dict[str, str]]:
    return _runtime_build_ytdlp_process_env(js_runtime)


def _emit_download_progress(
    progress_callback: DownloadProgressCallback,
    *,
    phase: str,
    progress_percent: float,
    detail: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "phase": phase,
            "progress_percent": progress_percent,
            "detail": detail,
        }
    )
