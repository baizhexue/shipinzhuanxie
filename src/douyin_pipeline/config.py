from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import os
import shlex
import shutil
import sys
from typing import Optional


@dataclass(frozen=True)
class Settings:
    output_dir: Path
    cookies_file: Optional[Path]
    cookies_from_browser: Optional[str]
    ffmpeg_cmd: tuple[str, ...]
    ytdlp_cmd: tuple[str, ...]
    whisper_model: str
    whisper_device: str
    openclaw_token: Optional[str]
    whisper_language: Optional[str] = None
    whisper_beam_size: int = 5
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: int = 120


def load_settings(
    *,
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    whisper_model: Optional[str] = None,
    whisper_device: Optional[str] = None,
    whisper_language: Optional[str] = None,
    whisper_beam_size: Optional[int] = None,
) -> Settings:
    env_output_dir = os.getenv("APP_OUTPUT_DIR", "output")
    env_ffmpeg_bin = os.getenv("FFMPEG_BIN") or _discover_ffmpeg_command()
    env_ytdlp_bin = os.getenv("YTDLP_BIN") or _discover_ytdlp_command()
    env_whisper_model = os.getenv("WHISPER_MODEL", "medium")
    env_whisper_device = os.getenv("WHISPER_DEVICE", "auto")
    env_whisper_language = os.getenv("WHISPER_LANGUAGE")
    env_whisper_beam_size = max(int(os.getenv("WHISPER_BEAM_SIZE", "5") or "5"), 1)
    env_cookies_file = os.getenv("DOUYIN_COOKIES_FILE")
    env_cookies_browser = os.getenv("DOUYIN_COOKIES_BROWSER")
    env_openclaw_token = os.getenv("OPENCLAW_SHARED_TOKEN")
    env_deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    env_deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    env_deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    env_deepseek_timeout_seconds = max(int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120") or "120"), 30)

    resolved_cookies = cookies_file or env_cookies_file
    resolved_browser = cookies_from_browser or env_cookies_browser

    return Settings(
        output_dir=Path(output_dir or env_output_dir).resolve(),
        cookies_file=Path(resolved_cookies).resolve() if resolved_cookies else None,
        cookies_from_browser=resolved_browser or None,
        ffmpeg_cmd=_parse_command(env_ffmpeg_bin),
        ytdlp_cmd=_parse_command(env_ytdlp_bin),
        whisper_model=whisper_model or env_whisper_model,
        whisper_device=whisper_device or env_whisper_device,
        openclaw_token=env_openclaw_token or None,
        whisper_language=_normalize_whisper_language(
            whisper_language if whisper_language is not None else env_whisper_language
        ),
        whisper_beam_size=max(
            int(whisper_beam_size if whisper_beam_size is not None else env_whisper_beam_size),
            1,
        ),
        deepseek_api_key=(env_deepseek_api_key or "").strip() or None,
        deepseek_base_url=_normalize_base_url(env_deepseek_base_url),
        deepseek_model=(env_deepseek_model or "deepseek-chat").strip() or "deepseek-chat",
        deepseek_timeout_seconds=env_deepseek_timeout_seconds,
    )


def _discover_ytdlp_command() -> str:
    for candidate in _ytdlp_candidates():
        if candidate.exists():
            return str(candidate)

    discovered = shutil.which("yt-dlp")
    if discovered:
        return discovered

    venv_script = _venv_script("yt-dlp")
    if venv_script:
        return str(venv_script)

    if importlib.util.find_spec("yt_dlp") is not None:
        return f'"{sys.executable}" -m yt_dlp'

    return "yt-dlp"


def _ytdlp_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/bin/yt-dlp",
        Path("/usr/local/bin/yt-dlp"),
        Path("/opt/homebrew/bin/yt-dlp"),
    ]


def _discover_ffmpeg_command() -> str:
    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered

    imageio_ffmpeg = _discover_imageio_ffmpeg()
    if imageio_ffmpeg:
        return imageio_ffmpeg

    for candidate in _ffmpeg_candidates():
        if candidate.exists():
            return str(candidate)

    return "ffmpeg"


def _ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    local_appdata = Path(os.getenv("LOCALAPPDATA", ""))
    program_files = Path(os.getenv("ProgramFiles", ""))

    if local_appdata:
        candidates.extend(
            sorted(
                (local_appdata / "Microsoft/WinGet/Packages").glob(
                    "Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"
                ),
                reverse=True,
            )
        )

    if program_files:
        candidates.extend(
            [
                program_files / "ffmpeg/bin/ffmpeg.exe",
                program_files / "FFmpeg/bin/ffmpeg.exe",
            ]
        )

    scoop_root = Path.home() / "scoop/apps/ffmpeg/current/bin/ffmpeg.exe"
    candidates.append(scoop_root)
    return candidates


def _discover_imageio_ffmpeg() -> Optional[str]:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None

    return imageio_ffmpeg.get_ffmpeg_exe()


def _venv_script(name: str) -> Optional[Path]:
    script_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    candidate = script_dir / f"{name}{suffix}"
    return candidate if candidate.exists() else None


def _parse_command(value: str) -> tuple[str, ...]:
    parts = tuple(shlex.split(value, posix=False))
    if not parts:
        raise ValueError("Command configuration cannot be empty.")
    return parts


def _normalize_whisper_language(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    text = value.strip().lower()
    if not text or text == "auto":
        return None
    return text


def _normalize_base_url(value: str) -> str:
    text = value.strip()
    if not text:
        return "https://api.deepseek.com"
    return text.rstrip("/")
