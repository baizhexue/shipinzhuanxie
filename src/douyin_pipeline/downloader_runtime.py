from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from douyin_pipeline.subprocess_utils import run_command


def detect_ytdlp_js_runtime(
    *,
    which: Callable[[str], Optional[str]] | None = None,
    home_factory: Callable[[], Path] | None = None,
) -> Optional[str]:
    which = which or shutil.which
    home_factory = home_factory or Path.home

    node_on_path = which("node")
    if node_on_path:
        return "node"

    node_candidate = find_common_js_runtime_path("node", home_factory=home_factory)
    if node_candidate:
        return f"node:{node_candidate}"

    deno_on_path = which("deno")
    if deno_on_path:
        return "deno"

    deno_candidate = find_common_js_runtime_path("deno", home_factory=home_factory)
    if deno_candidate:
        return f"deno:{deno_candidate}"

    return None


def find_common_js_runtime_path(
    name: str,
    *,
    home_factory: Callable[[], Path] | None = None,
) -> Optional[str]:
    home_factory = home_factory or Path.home
    home = home_factory()
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


def ytdlp_supports_js_runtimes(command: tuple[str, ...], *, timeout: int) -> bool:
    try:
        completed = run_command(
            [*command, "--help"],
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False

    help_text = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return "--js-runtimes" in help_text


def can_use_deno_compat_mode(js_runtime: str) -> bool:
    return js_runtime == "deno" or js_runtime.startswith("deno:")


def build_ytdlp_process_env(js_runtime: str) -> Optional[dict[str, str]]:
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
