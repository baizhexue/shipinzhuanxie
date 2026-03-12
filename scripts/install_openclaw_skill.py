from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the OpenClaw video transcript skill.")
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1] / "openclaw_skill" / "video-transcript-bridge"),
        help="source skill directory",
    )
    parser.add_argument(
        "--dest-root",
        default=str(Path.home() / ".openclaw" / "skills"),
        help="OpenClaw skills root directory",
    )
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

    if dest.exists():
        if not args.force:
            raise SystemExit(f"Skill destination already exists: {dest}")
        shutil.rmtree(dest)

    shutil.copytree(source, dest)
    print(f"Installed OpenClaw skill to: {dest}")
    print("Next step: merge openclaw.config.example.json into ~/.openclaw/openclaw.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
