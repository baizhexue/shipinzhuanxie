from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Call the LAN video transcript service.")
    parser.add_argument("--input-file", required=True, help="UTF-8 text file with raw video link/share text")
    parser.add_argument("--api-url", default=os.environ.get("VIDEO_TRANSCRIPT_API_URL", "").strip())
    parser.add_argument("--token", default=os.environ.get("VIDEO_TRANSCRIPT_API_TOKEN", "").strip())
    args = parser.parse_args()

    raw_input = Path(args.input_file).read_text(encoding="utf-8").strip()
    if not raw_input:
        raise SystemExit("input file is empty")
    if not args.api_url:
        raise SystemExit("VIDEO_TRANSCRIPT_API_URL is not configured")
    if not args.token:
        raise SystemExit("VIDEO_TRANSCRIPT_API_TOKEN is not configured")

    url = args.api_url.rstrip("/") + "/api/openclaw/transcribe"
    payload = json.dumps({"raw_input": raw_input}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-OpenClaw-Token": args.token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            body = response.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(body or json.dumps({"detail": f"HTTP {exc.code}"}), file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(json.dumps({"detail": f"request failed: {exc.reason}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
