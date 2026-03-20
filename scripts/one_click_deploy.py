from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DOCKER_PORT = 4444


def main() -> int:
    parser = argparse.ArgumentParser(description="One-click deploy helper for 视频转写助手.")
    parser.add_argument(
        "--mode",
        choices=("auto", "docker", "local"),
        default="auto",
        help="deployment mode; auto prefers Docker when available",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host for local mode")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="bind port for local mode")
    parser.add_argument(
        "--skip-asr",
        action="store_true",
        help="install web dependencies only; skip ASR dependencies",
    )
    parser.add_argument(
        "--skip-browser-install",
        action="store_true",
        help="skip `playwright install chromium` during local deployment",
    )
    parser.add_argument(
        "--with-telegram",
        action="store_true",
        help="start Telegram profile too when Docker mode is used",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    _ensure_env_file(repo_root)

    mode = args.mode
    if mode == "auto":
        mode = "docker" if _docker_available() else "local"

    if mode == "docker":
        _deploy_with_docker(repo_root, with_telegram=args.with_telegram)
        _print_success("docker", host="127.0.0.1", port=DOCKER_PORT)
        return 0

    _deploy_locally(
        repo_root,
        host=args.host,
        port=args.port,
        with_asr=not args.skip_asr,
        install_browser=not args.skip_browser_install,
    )
    return 0


def _deploy_with_docker(repo_root: Path, *, with_telegram: bool) -> None:
    command = ["docker", "compose"]
    if with_telegram:
        command.extend(["--profile", "telegram"])
    command.extend(["up", "--build", "-d", "web"])
    if with_telegram:
        command.append("telegram")
    _run(command, cwd=repo_root)


def _deploy_locally(
    repo_root: Path,
    *,
    host: str,
    port: int,
    with_asr: bool,
    install_browser: bool,
) -> None:
    python_command = _discover_python()
    venv_dir = repo_root / ".venv"
    if not venv_dir.exists():
        _run(python_command + ["-m", "venv", str(venv_dir)], cwd=repo_root)

    venv_python = _venv_python(venv_dir)
    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=repo_root)

    extras = "web,asr" if with_asr else "web"
    _run([str(venv_python), "-m", "pip", "install", f"-e", f".[{extras}]"], cwd=repo_root)

    if install_browser:
        _run([str(venv_python), "-m", "playwright", "install", "chromium"], cwd=repo_root)

    doctor_args = [str(venv_python), "-m", "douyin_pipeline.cli", "doctor"]
    if not with_asr:
        doctor_args.append("--skip-asr")
    _run(doctor_args, cwd=repo_root)

    _print_success("local", host=host, port=port)
    _run(
        [str(venv_python), "-m", "douyin_pipeline.web", "--host", host, "--port", str(port)],
        cwd=repo_root,
    )


def _ensure_env_file(repo_root: Path) -> None:
    env_file = repo_root / ".env"
    env_example = repo_root / ".env.example"
    if env_file.exists() or not env_example.exists():
        return
    env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")


def _discover_python() -> list[str]:
    candidates: list[list[str]] = []
    if shutil.which("py"):
        candidates.append(["py", "-3"])
    if shutil.which("python"):
        candidates.append(["python"])
    if shutil.which("python3"):
        candidates.append(["python3"])

    for candidate in candidates:
        try:
            completed = subprocess.run(
                candidate + ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if completed.returncode == 0:
            return candidate

    raise RuntimeError("未找到 Python 3.9+。请先安装 Python 3.9 或更高版本。")


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        compose = subprocess.run(
            ["docker", "compose", "version"],
            check=False,
            capture_output=True,
            text=True,
        )
        info = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return compose.returncode == 0 and info.returncode == 0


def _print_success(mode: str, *, host: str, port: int) -> None:
    print("")
    print("=" * 72)
    print(f"视频转写助手已切换到 {mode} 部署流程。")
    print(f"访问地址: http://{host}:{port}")
    if mode == "local":
        print("当前终端将继续占用并运行 Web 服务。按 Ctrl+C 可停止。")
    else:
        print("Docker 已在后台启动服务。")
    print("=" * 72)
    print("")


def _run(command: list[str], *, cwd: Path) -> None:
    printable = " ".join(command)
    print(f"[run] {printable}")
    subprocess.run(command, cwd=cwd, check=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
