from __future__ import annotations

import argparse
import json
import secrets
import shutil
from pathlib import Path
from typing import Any


DEFAULT_SKILL_NAME = "video-transcript-bridge"
DEFAULT_LOCAL_API_URL = "http://127.0.0.1:4455"
DEFAULT_LAN_API_URL = "http://192.168.50.201:4455"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and configure the OpenClaw video transcript skill.")
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1] / "skills" / DEFAULT_SKILL_NAME),
        help="source skill directory",
    )
    parser.add_argument(
        "--dest-root",
        default=str(Path.home() / ".openclaw" / "workspace" / "skills"),
        help="OpenClaw skills root directory",
    )
    parser.add_argument(
        "--openclaw-config",
        default=str(Path.home() / ".openclaw" / "openclaw.json"),
        help="path to openclaw.json",
    )
    parser.add_argument(
        "--service-env-file",
        default=str(Path(__file__).resolve().parents[1] / ".env"),
        help="service .env file to keep OPENCLAW_SHARED_TOKEN in sync",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "lan"),
        default="local",
        help="local: OpenClaw and the service are on the same machine; lan: OpenClaw calls another machine",
    )
    parser.add_argument("--api-url", default="", help="override service URL")
    parser.add_argument("--token", default="", help="override shared token")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the existing installed skill directory",
    )
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Skill source directory not found: {source}")

    dest_root = Path(args.dest_root).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / source.name
    install_skill(source, dest, force=args.force)

    config_path = Path(args.openclaw_config).expanduser().resolve()
    config = load_json_file(config_path, default={})

    env_file_path = Path(args.service_env_file).expanduser().resolve()
    env_values = load_env_file(env_file_path)

    api_url = (
        args.api_url.strip()
        or existing_skill_env(config).get("VIDEO_TRANSCRIPT_API_URL", "").strip()
        or (DEFAULT_LOCAL_API_URL if args.mode == "local" else DEFAULT_LAN_API_URL)
    )
    token = (
        args.token.strip()
        or env_values.get("OPENCLAW_SHARED_TOKEN", "").strip()
        or existing_skill_env(config).get("VIDEO_TRANSCRIPT_API_TOKEN", "").strip()
        or generate_shared_token()
    )

    save_openclaw_skill_env(config_path, config, api_url=api_url, token=token)

    if args.mode == "local":
        write_env_value(env_file_path, "OPENCLAW_SHARED_TOKEN", token)

    print(f"Installed OpenClaw skill to: {dest}")
    print(f"OpenClaw config updated: {config_path}")
    print(f"VIDEO_TRANSCRIPT_API_URL={api_url}")
    print("VIDEO_TRANSCRIPT_API_TOKEN has been written automatically.")
    if args.mode == "local":
        print(f"OPENCLAW_SHARED_TOKEN synced to: {env_file_path}")
    else:
        print(f"Generated token: {token}")
        print("LAN mode: copy this token to the service-side OPENCLAW_SHARED_TOKEN.")
    return 0


def install_skill(source: Path, dest: Path, *, force: bool) -> None:
    if dest.exists():
        if not force:
            raise SystemExit(f"Skill destination already exists: {dest}")
        shutil.rmtree(dest)
    shutil.copytree(source, dest)


def load_json_file(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def save_openclaw_skill_env(
    config_path: Path,
    config: dict[str, Any],
    *,
    api_url: str,
    token: str,
) -> None:
    skills = config.setdefault("skills", {})
    entries = skills.setdefault("entries", {})
    skill_entry = entries.setdefault(DEFAULT_SKILL_NAME, {})
    env = skill_entry.setdefault("env", {})
    env["VIDEO_TRANSCRIPT_API_URL"] = api_url
    env["VIDEO_TRANSCRIPT_API_TOKEN"] = token

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def existing_skill_env(config: dict[str, Any]) -> dict[str, str]:
    return (
        config.get("skills", {})
        .get("entries", {})
        .get(DEFAULT_SKILL_NAME, {})
        .get("env", {})
    )


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            updated_lines.append(f"{key}={value}")
            found = True
        else:
            updated_lines.append(line)

    if not found:
        updated_lines.append(f"{key}={value}")

    path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


def generate_shared_token() -> str:
    return secrets.token_urlsafe(24)


if __name__ == "__main__":
    raise SystemExit(main())
