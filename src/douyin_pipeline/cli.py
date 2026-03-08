from __future__ import annotations

import argparse
from pathlib import Path
import sys

from douyin_pipeline.config import load_settings
from douyin_pipeline.doctor import has_failures, run_checks, summarize_results
from douyin_pipeline.pipeline import process_job
from douyin_pipeline.transcriber import transcribe_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-pipeline",
        description="Download a Douyin video and transcribe it into text.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="download and transcribe")
    _add_shared_download_args(run_parser)

    download_parser = subparsers.add_parser("download", help="download only")
    _add_shared_download_args(download_parser)

    transcribe_parser = subparsers.add_parser("transcribe", help="transcribe a local video")
    transcribe_parser.add_argument("video_path", help="local video path")
    _add_runtime_args(transcribe_parser)

    doctor_parser = subparsers.add_parser("doctor", help="check local runtime dependencies")
    _add_runtime_args(doctor_parser)
    doctor_parser.add_argument(
        "--skip-asr",
        action="store_true",
        help="skip faster-whisper import check",
    )

    web_parser = subparsers.add_parser("web", help="start local web ui")
    _add_runtime_args(web_parser)
    web_parser.add_argument("--host", default="127.0.0.1", help="bind host")
    web_parser.add_argument("--port", default=8000, type=int, help="bind port")

    telegram_parser = subparsers.add_parser("telegram-bot", help="start telegram bot long polling")
    _add_runtime_args(telegram_parser)
    telegram_parser.add_argument("--token", default=None, help="telegram bot token")
    telegram_parser.add_argument(
        "--allowed-chat-id",
        action="append",
        dest="allowed_chat_ids",
        type=int,
        default=None,
        help="restrict bot access to a specific Telegram chat id; repeatable",
    )
    telegram_parser.add_argument(
        "--public-base-url",
        default=None,
        help="public web base url used to send result links back to Telegram",
    )
    telegram_parser.add_argument(
        "--state-path",
        default=None,
        help="bot offset state file path",
    )
    telegram_parser.add_argument(
        "--poll-timeout",
        default=25,
        type=int,
        help="Telegram getUpdates long polling timeout in seconds",
    )
    telegram_parser.add_argument(
        "--retry-delay",
        default=3.0,
        type=float,
        help="retry delay in seconds after polling errors",
    )
    telegram_parser.add_argument(
        "--no-progress-updates",
        action="store_true",
        help="disable Telegram progress updates while a job is running",
    )

    return parser


def _add_shared_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("raw_input", help="Douyin share text or URL")
    _add_runtime_args(parser)


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--cookies", default=None, help="cookies.txt path")
    parser.add_argument(
        "--browser-cookies",
        default=None,
        choices=["chrome", "edge", "firefox"],
        help="read cookies from a local browser",
    )
    parser.add_argument("--model", default=None, help="whisper model name")
    parser.add_argument("--device", default=None, help="whisper device, e.g. auto/cpu/cuda")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = load_settings(
            output_dir=getattr(args, "out", None),
            cookies_file=getattr(args, "cookies", None),
            cookies_from_browser=getattr(args, "browser_cookies", None),
            whisper_model=getattr(args, "model", None),
            whisper_device=getattr(args, "device", None),
        )
        settings.output_dir.mkdir(parents=True, exist_ok=True)

        if args.command == "doctor":
            results = run_checks(settings, with_asr=not args.skip_asr)
            print(summarize_results(results))
            return 1 if has_failures(results) else 0

        if args.command == "download":
            job = process_job(args.raw_input, settings, action="download")
            print(f"video: {job['video_path']}")
            return 0

        if args.command == "run":
            job = process_job(args.raw_input, settings, action="run")
            print(f"video: {job['video_path']}")
            print(f"audio: {job['audio_path']}")
            print(f"text: {job['transcript_path']}")
            return 0

        if args.command == "transcribe":
            transcript_result = transcribe_video(Path(args.video_path).resolve(), settings)
            print(f"audio: {transcript_result.audio_path}")
            print(f"text: {transcript_result.transcript_path}")
            return 0

        if args.command == "web":
            from douyin_pipeline.web import start_server

            start_server(settings, host=args.host, port=args.port)
            return 0

        if args.command == "telegram-bot":
            from douyin_pipeline.telegram_bot import load_telegram_settings, start_bot

            bot_settings = load_telegram_settings(
                settings,
                token=args.token,
                allowed_chat_ids=getattr(args, "allowed_chat_ids", None),
                public_base_url=args.public_base_url,
                state_path=args.state_path,
                poll_timeout=args.poll_timeout,
                retry_delay=args.retry_delay,
                progress_updates=not args.no_progress_updates,
            )
            start_bot(settings, bot_settings)
            return 0

        parser.error(f"unknown command: {args.command}")
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
