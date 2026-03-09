from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.parser import detect_source_platform


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
        platform = detect_source_platform(source_url)
        if _should_use_douyin_browser_fallback(source_url, exc):
            from douyin_pipeline.douyin_browser import download_with_browser

            return download_with_browser(source_url, job_dir)
        if _should_use_xiaohongshu_page_fallback(platform, exc):
            from douyin_pipeline.xiaohongshu_page import download_with_page

            return download_with_page(source_url, job_dir)
        if _should_use_kuaishou_page_fallback(platform, exc):
            from douyin_pipeline.kuaishou_page import download_with_page

            return download_with_page(source_url, job_dir)
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

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=process_env,
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


def _should_use_douyin_browser_fallback(source_url: str, error: RuntimeError) -> bool:
    text = str(error)
    return (
        "douyin.com" in source_url
        and "Fresh cookies" in text
    )


def _should_use_xiaohongshu_page_fallback(platform: str, error: RuntimeError) -> bool:
    return platform == "xiaohongshu"


def _should_use_kuaishou_page_fallback(platform: str, error: RuntimeError) -> bool:
    return platform == "kuaishou"


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
    node_on_path = shutil.which("node")
    if node_on_path:
        return "node"

    node_candidate = _find_common_js_runtime_path("node")
    if node_candidate:
        return f"node:{node_candidate}"

    deno_on_path = shutil.which("deno")
    if deno_on_path:
        return "deno"

    deno_candidate = _find_common_js_runtime_path("deno")
    if deno_candidate:
        return f"deno:{deno_candidate}"

    return None


def _find_common_js_runtime_path(name: str) -> Optional[str]:
    home = Path.home()
    candidates = []

    if name == "node":
        candidates.extend(
            [
                Path("/opt/homebrew/bin/node"),
                Path("/usr/local/bin/node"),
                home / ".local/bin/node",
            ]
        )
    elif name == "deno":
        candidates.extend(
            [
                home / ".deno/bin/deno",
                home / ".local/bin/deno",
                Path("/opt/homebrew/bin/deno"),
                Path("/usr/local/bin/deno"),
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    return None


def _ytdlp_supports_js_runtimes(command: tuple[str, ...]) -> bool:
    try:
        completed = subprocess.run(
            [*command, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
    except (FileNotFoundError, OSError):
        return False

    help_text = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return "--js-runtimes" in help_text


def _can_use_deno_compat_mode(js_runtime: str) -> bool:
    return js_runtime == "deno" or js_runtime.startswith("deno:")


def _build_ytdlp_process_env(js_runtime: str) -> Optional[dict[str, str]]:
    if not js_runtime.startswith("deno:"):
        return None

    _, _, runtime_path = js_runtime.partition(":")
    if not runtime_path:
        return None

    runtime_dir = str(Path(runtime_path).expanduser().resolve().parent)
    env = os.environ.copy()
    existing_path = env.get("PATH", "")
    env["PATH"] = runtime_dir if not existing_path else f"{runtime_dir}{os.pathsep}{existing_path}"
    return env
