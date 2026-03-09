from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib
import subprocess
import sys
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.downloader import _detect_ytdlp_js_runtime, _ytdlp_supports_js_runtimes


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_checks(settings: Settings, *, with_asr: bool = True) -> list[CheckResult]:
    results = [
        _check_python(),
        _check_command("yt-dlp", settings.ytdlp_cmd, ["--version"]),
        _check_command("ffmpeg", settings.ffmpeg_cmd, ["-version"]),
        _check_youtube_js_runtime(settings.ytdlp_cmd),
        _check_output_dir(settings.output_dir),
        _check_cookies(settings.cookies_file, settings.cookies_from_browser),
    ]

    if with_asr:
        results.append(_check_python_module("faster_whisper", "pip install -e .[asr]"))
        results.append(_check_python_module("opencc", "pip install -e .[asr] --upgrade"))

    return results


def summarize_results(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"[{status}] {result.name}: {result.detail}")
    return "\n".join(lines)


def has_failures(results: list[CheckResult]) -> bool:
    return any(not result.ok for result in results)


def _check_python() -> CheckResult:
    version = sys.version_info
    ok = version >= (3, 9)
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if not ok:
        detail = f"{detail} (requires >= 3.9)"
    return CheckResult(name="python", ok=ok, detail=detail)


def _check_command(name: str, command: tuple[str, ...], version_args: list[str]) -> CheckResult:
    try:
        completed = subprocess.run(
            [*command, *version_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            ok=False,
            detail=f"command not found: {' '.join(command)}",
        )
    except OSError as exc:
        return CheckResult(name=name, ok=False, detail=str(exc))

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        return CheckResult(name=name, ok=False, detail=stderr)

    first_line = _first_non_empty_line(completed.stdout) or _first_non_empty_line(completed.stderr)
    return CheckResult(name=name, ok=True, detail=first_line or "available")


def _check_output_dir(output_dir: Path) -> CheckResult:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(name="output_dir", ok=False, detail=str(exc))

    return CheckResult(name="output_dir", ok=True, detail=str(output_dir))


def _check_youtube_js_runtime(ytdlp_cmd: tuple[str, ...]) -> CheckResult:
    runtime = _detect_ytdlp_js_runtime()
    if not runtime:
        return CheckResult(
            name="youtube_js_runtime",
            ok=False,
            detail="not found; install node or deno for stable YouTube downloads",
        )

    if not _ytdlp_supports_js_runtimes(ytdlp_cmd):
        if runtime == "deno" or runtime.startswith("deno:"):
            return CheckResult(
                name="youtube_js_runtime",
                ok=True,
                detail=f"{runtime} (compat mode for older yt-dlp)",
            )
        return CheckResult(
            name="youtube_js_runtime",
            ok=False,
            detail="runtime found, but yt-dlp is too old for node-based YouTube support; install deno or upgrade yt-dlp",
        )

    return CheckResult(name="youtube_js_runtime", ok=True, detail=runtime)


def _check_cookies(
    cookies_file: Optional[Path],
    cookies_from_browser: Optional[str],
) -> CheckResult:
    if cookies_from_browser:
        return CheckResult(name="cookies", ok=True, detail=f"browser:{cookies_from_browser}")

    if cookies_file is None:
        return CheckResult(name="cookies", ok=True, detail="not configured")

    if not cookies_file.exists():
        return CheckResult(name="cookies", ok=False, detail=f"missing: {cookies_file}")

    if not cookies_file.is_file():
        return CheckResult(name="cookies", ok=False, detail=f"not a file: {cookies_file}")

    return CheckResult(name="cookies", ok=True, detail=str(cookies_file))


def _check_python_module(module_name: str, install_hint: str) -> CheckResult:
    try:
        importlib.import_module(module_name)
    except ImportError:
        return CheckResult(name=module_name, ok=False, detail=f"not installed; run `{install_hint}`")

    return CheckResult(name=module_name, ok=True, detail="import ok")


def _first_non_empty_line(value: str) -> str:
    for line in value.splitlines():
        text = line.strip()
        if text:
            return text
    return ""
