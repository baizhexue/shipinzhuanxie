from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 7200


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Call the LAN video transcription service for OpenClaw."
    )
    parser.add_argument("--input", default="", help="video URL or full share text")
    parser.add_argument("--input-file", default="", help="UTF-8 text file with the raw input")
    parser.add_argument("--api-url", default=os.getenv("VIDEO_TRANSCRIPT_API_URL", "").strip())
    parser.add_argument("--token", default=os.getenv("VIDEO_TRANSCRIPT_API_TOKEN", "").strip())
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--healthcheck", action="store_true", help="check remote skill bridge health")
    args = parser.parse_args()

    api_url = (args.api_url or "").rstrip("/")
    if not api_url:
        return _fail(
            "missing_api_url",
            "缺少 VIDEO_TRANSCRIPT_API_URL，无法调用局域网转写服务。",
        )

    if args.healthcheck:
        return _run_healthcheck(api_url, args.token, args.timeout_seconds)

    raw_input = _resolve_raw_input(args.input, args.input_file)
    if not raw_input:
        return _fail(
            "missing_input",
            "请通过 --input 或 --input-file 提供视频链接或完整分享文案。",
        )

    try:
        payload = _request_json(
            f"{api_url}/api/openclaw/transcribe",
            method="POST",
            token=args.token,
            timeout_seconds=args.timeout_seconds,
            json_payload={"raw_input": raw_input},
        )
    except urllib.error.HTTPError as exc:
        return _fail_http(exc)
    except urllib.error.URLError as exc:
        return _fail("network_error", f"请求转写服务失败：{exc.reason}")
    except FileNotFoundError as exc:
        return _fail("input_file_missing", str(exc))
    except TimeoutError:
        return _fail("request_timeout", "等待转写服务返回超时。")

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


def _resolve_raw_input(direct_value: str, input_file: str) -> str:
    if direct_value.strip():
        return direct_value.strip()
    if not input_file:
        return ""

    path = Path(input_file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _run_healthcheck(api_url: str, token: str, timeout_seconds: int) -> int:
    try:
        payload = _request_json(
            f"{api_url}/api/openclaw/health",
            method="GET",
            token=token,
            timeout_seconds=timeout_seconds,
            json_payload=None,
        )
    except urllib.error.HTTPError as exc:
        return _fail_http(exc)
    except urllib.error.URLError as exc:
        return _fail("network_error", f"请求健康检查失败：{exc.reason}")
    except TimeoutError:
        return _fail("request_timeout", "等待健康检查返回超时。")

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


def _request_json(
    url: str,
    *,
    method: str,
    token: str,
    timeout_seconds: int,
    json_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-OpenClaw-Token"] = token

    data = None
    if json_payload is not None:
        data = json.dumps(json_payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _fail_http(exc: urllib.error.HTTPError) -> int:
    detail = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = {
            "error_code": "http_error",
            "detail": detail or f"HTTP {exc.code}",
        }
    if "status_code" not in payload:
        payload["status_code"] = exc.code
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 1


def _fail(code: str, detail: str) -> int:
    sys.stdout.write(
        json.dumps(
            {
                "error_code": code,
                "detail": detail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.stdout.write("\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
