from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from typing import Any, Iterable, Optional
import json
import mimetypes
import uuid
import urllib.error
import urllib.request

from douyin_pipeline.config import Settings
from douyin_pipeline.errors import classify_exception
from douyin_pipeline.jobs import read_manifest, to_public_job
from douyin_pipeline.parser import extract_share_url
from douyin_pipeline.pipeline import prepare_job, run_prepared_job


DEFAULT_ALLOWED_UPDATES = ("message",)
DEFAULT_POLL_TIMEOUT = 25
DEFAULT_RETRY_DELAY = 3.0
DEFAULT_MESSAGE_LIMIT = 3900
DEFAULT_TRANSCRIPT_PREVIEW_LIMIT = 3500


@dataclass(frozen=True)
class TelegramBotSettings:
    token: str
    allowed_chat_ids: tuple[int, ...]
    public_base_url: Optional[str]
    state_path: Path
    poll_timeout: int = DEFAULT_POLL_TIMEOUT
    retry_delay: float = DEFAULT_RETRY_DELAY
    progress_updates: bool = True


def load_telegram_settings(
    app_settings: Settings,
    *,
    token: Optional[str] = None,
    allowed_chat_ids: Optional[Iterable[int]] = None,
    public_base_url: Optional[str] = None,
    state_path: Optional[str] = None,
    poll_timeout: int = DEFAULT_POLL_TIMEOUT,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    progress_updates: bool = True,
) -> TelegramBotSettings:
    import os

    resolved_token = (token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not resolved_token:
        raise ValueError("Telegram bot token is required. Set TELEGRAM_BOT_TOKEN or pass --token.")

    env_allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    resolved_allowed = tuple(allowed_chat_ids or _parse_allowed_chat_ids(env_allowed))
    resolved_public_base_url = public_base_url or os.getenv("DOUYIN_PUBLIC_BASE_URL")
    env_progress_updates = os.getenv("TELEGRAM_PROGRESS_UPDATES", "")
    resolved_state_path = Path(
        state_path
        or os.getenv("TELEGRAM_STATE_PATH")
        or (app_settings.output_dir / "telegram_bot_state.json")
    ).expanduser().resolve()
    resolved_progress_updates = (
        progress_updates
        if env_progress_updates == ""
        else env_progress_updates.strip().lower() not in {"0", "false", "no", "off"}
    )

    return TelegramBotSettings(
        token=resolved_token,
        allowed_chat_ids=resolved_allowed,
        public_base_url=_normalize_public_base_url(resolved_public_base_url),
        state_path=resolved_state_path,
        poll_timeout=max(int(poll_timeout), 1),
        retry_delay=max(float(retry_delay), 1.0),
        progress_updates=bool(resolved_progress_updates),
    )


def start_bot(app_settings: Settings, bot_settings: TelegramBotSettings) -> None:
    client = TelegramBotClient(bot_settings)
    runner = TelegramBotRunner(app_settings, bot_settings, client)
    runner.run_forever()


def main() -> int:
    import argparse

    from douyin_pipeline.config import load_settings

    parser = argparse.ArgumentParser(description="Start Telegram bot long polling.")
    parser.add_argument("--token", default=None, help="telegram bot token")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--cookies", default=None, help="cookies.txt path")
    parser.add_argument(
        "--browser-cookies",
        default=None,
        choices=["chrome", "edge", "firefox"],
        help="read cookies from a local browser",
    )
    parser.add_argument("--model", default=None, help="whisper model name")
    parser.add_argument("--device", default=None, help="whisper device")
    parser.add_argument(
        "--allowed-chat-id",
        action="append",
        dest="allowed_chat_ids",
        type=int,
        default=None,
        help="restrict bot access to a specific Telegram chat id; repeatable",
    )
    parser.add_argument("--public-base-url", default=None, help="public result base url")
    parser.add_argument("--state-path", default=None, help="bot state file path")
    parser.add_argument("--poll-timeout", default=25, type=int, help="getUpdates timeout seconds")
    parser.add_argument("--retry-delay", default=3.0, type=float, help="retry delay seconds")
    parser.add_argument(
        "--no-progress-updates",
        action="store_true",
        help="disable Telegram progress updates while a job is running",
    )
    args = parser.parse_args()

    app_settings = load_settings(
        output_dir=args.out,
        cookies_file=args.cookies,
        cookies_from_browser=args.browser_cookies,
        whisper_model=args.model,
        whisper_device=args.device,
    )
    app_settings.output_dir.mkdir(parents=True, exist_ok=True)
    bot_settings = load_telegram_settings(
        app_settings,
        token=args.token,
        allowed_chat_ids=args.allowed_chat_ids,
        public_base_url=args.public_base_url,
        state_path=args.state_path,
        poll_timeout=args.poll_timeout,
        retry_delay=args.retry_delay,
        progress_updates=not args.no_progress_updates,
    )
    start_bot(app_settings, bot_settings)
    return 0


class TelegramBotRunner:
    def __init__(
        self,
        app_settings: Settings,
        bot_settings: TelegramBotSettings,
        client: "TelegramBotClient",
    ) -> None:
        self._app_settings = app_settings
        self._bot_settings = bot_settings
        self._client = client
        self._state = _load_state(bot_settings.state_path)
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run_forever(self) -> None:
        self._client.delete_webhook()
        bot_profile = self._client.get_me()
        print(
            f"telegram bot ready: @{bot_profile.get('username', 'unknown')} "
            f"(allowed_chats={self._bot_settings.allowed_chat_ids or 'all'})"
        )

        while not self._stop_requested:
            try:
                updates = self._client.get_updates(
                    offset=self._state.get("offset"),
                    timeout=self._bot_settings.poll_timeout,
                    allowed_updates=DEFAULT_ALLOWED_UPDATES,
                )
                self._handle_updates(updates)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                if self._stop_requested:
                    break
                print(f"telegram bot poll error: {exc}")
                sleep(self._bot_settings.retry_delay)

    def _handle_updates(self, updates: list[dict[str, Any]]) -> None:
        for update in updates:
            if self._stop_requested:
                return
            update_id = int(update["update_id"])
            self._state["offset"] = update_id + 1
            _save_state(self._bot_settings.state_path, self._state)
            self._handle_update(update)

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat") or {}
        chat_id = int(chat.get("id"))
        text = _extract_message_text(message)

        if self._bot_settings.allowed_chat_ids and chat_id not in self._bot_settings.allowed_chat_ids:
            print(f"telegram bot ignored unauthorized chat_id={chat_id}")
            return

        if not text:
            self._client.send_message(chat_id, _help_text())
            return

        normalized = text.strip()
        if normalized in {"/start", "/help"}:
            self._client.send_message(chat_id, _help_text())
            return

        if normalized == "/web":
            if not self._bot_settings.public_base_url:
                self._client.send_message(chat_id, "Web URL is not configured.")
                return
            self._client.send_message(chat_id, self._bot_settings.public_base_url)
            return

        try:
            extract_share_url(normalized)
        except ValueError:
            self._client.send_message(chat_id, _help_text())
            return

        thread = Thread(
            target=self._process_message_job,
            args=(chat_id, normalized),
            daemon=True,
        )
        thread.start()

    def _process_message_job(self, chat_id: int, raw_input: str) -> None:
        try:
            prepared_job = prepare_job(raw_input, self._app_settings, action="run")
        except Exception as exc:
            error_info = classify_exception(exc)
            self._client.send_message(chat_id, _build_failure_text(error_info.message, error_info.hint))
            return

        self._client.send_message(
            chat_id,
            f"Task received.\njob_id: {prepared_job.job_dir.name}\nStarting download and transcription.",
        )
        progress_reporter = TelegramProgressReporter(
            self._client,
            chat_id,
            enabled=self._bot_settings.progress_updates,
        )

        try:
            manifest = run_prepared_job(
                prepared_job,
                self._app_settings,
                status_callback=progress_reporter.handle_manifest,
            )
        except Exception as exc:
            failed_manifest = read_manifest(prepared_job.job_dir) or {
                "job_id": prepared_job.job_dir.name,
                "error": str(exc),
            }
            self._send_failure(chat_id, failed_manifest)
            return

        self._send_success(chat_id, manifest)

    def _send_failure(self, chat_id: int, manifest: dict[str, Any]) -> None:
        message_lines = [
            "Task failed.",
            f"job_id: {manifest.get('job_id', '-')}",
        ]

        if manifest.get("error"):
            message_lines.append(f"reason: {manifest['error']}")

        if manifest.get("error_hint"):
            message_lines.append(f"hint: {manifest['error_hint']}")

        self._client.send_message(chat_id, "\n".join(message_lines))

    def _send_success(self, chat_id: int, manifest: dict[str, Any]) -> None:
        public_job = to_public_job(manifest)
        summary_lines = [
            "Task completed.",
            f"job_id: {public_job.get('job_id', '-')}",
        ]

        title = public_job.get("title")
        if title:
            summary_lines.append(f"title: {title}")

        transcript_path = manifest.get("transcript_path")
        transcript_preview = manifest.get("transcript_preview") or ""

        if self._bot_settings.public_base_url:
            summary_lines.extend(_build_public_links(public_job, self._bot_settings.public_base_url))

        self._client.send_message(chat_id, "\n".join(summary_lines))

        if transcript_preview:
            self._client.send_message(
                chat_id,
                _truncate_text(transcript_preview, DEFAULT_TRANSCRIPT_PREVIEW_LIMIT),
            )

        if transcript_path:
            absolute_transcript_path = self._app_settings.output_dir / str(transcript_path)
            if absolute_transcript_path.exists():
                caption = f"Transcript file for {public_job.get('job_id', '-')}"
                try:
                    self._client.send_document(chat_id, absolute_transcript_path, caption=caption)
                except Exception as exc:
                    self._client.send_message(chat_id, f"Transcript file send failed: {exc}")


class TelegramBotClient:
    def __init__(self, settings: TelegramBotSettings) -> None:
        self._settings = settings
        self._base_url = f"https://api.telegram.org/bot{settings.token}"

    def get_me(self) -> dict[str, Any]:
        return self._json_request("getMe")

    def delete_webhook(self) -> None:
        self._json_request("deleteWebhook", payload={"drop_pending_updates": False})

    def get_updates(
        self,
        *,
        offset: Optional[int],
        timeout: int,
        allowed_updates: Iterable[str],
    ) -> list[dict[str, Any]]:
        payload = {
            "timeout": timeout,
            "allowed_updates": list(allowed_updates),
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._json_request("getUpdates", payload=payload)
        if not isinstance(result, list):
            raise RuntimeError("Telegram Bot API returned unexpected getUpdates payload.")
        return result

    def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        safe_text = _truncate_text(text, DEFAULT_MESSAGE_LIMIT)
        return self._json_request(
            "sendMessage",
            payload={
                "chat_id": chat_id,
                "text": safe_text,
                "disable_web_page_preview": True,
            },
        )

    def send_document(
        self,
        chat_id: int,
        document_path: Path,
        *,
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = _truncate_text(caption, 900)
        return self._multipart_request("sendDocument", fields=fields, file_field="document", file_path=document_path)

    def _json_request(
        self,
        method: str,
        *,
        payload: Optional[dict[str, Any]] = None,
    ) -> Any:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._settings.poll_timeout + 10) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram Bot API HTTP error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram Bot API request failed: {exc}") from exc

        if not response_payload.get("ok"):
            raise RuntimeError(response_payload.get("description", "Telegram Bot API request failed."))

        return response_payload.get("result")

    def _multipart_request(
        self,
        method: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> Any:
        boundary = f"----douyinpipeline{uuid.uuid4().hex}"
        body = bytearray()

        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            )

        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._settings.poll_timeout + 30) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram Bot API HTTP error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram Bot API request failed: {exc}") from exc

        if not response_payload.get("ok"):
            raise RuntimeError(response_payload.get("description", "Telegram Bot API request failed."))

        return response_payload.get("result")


def _extract_message_text(message: dict[str, Any]) -> str:
    text = message.get("text")
    if isinstance(text, str):
        return text

    caption = message.get("caption")
    if isinstance(caption, str):
        return caption

    return ""


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"offset": None}

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"offset": None}

    if not isinstance(payload, dict):
        return {"offset": None}

    return {"offset": payload.get("offset")}


def _save_state(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_allowed_chat_ids(raw_value: str) -> list[int]:
    values = []
    for item in raw_value.split(","):
        text = item.strip()
        if not text:
            continue
        values.append(int(text))
    return values


def _normalize_public_base_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.rstrip("/")


def _build_public_links(public_job: dict[str, Any], base_url: str) -> list[str]:
    lines = []
    for file_item in public_job.get("files", []):
        url = file_item.get("url")
        label = file_item.get("label", "File")
        if not url:
            continue
        lines.append(f"{label}: {base_url}{url}")
    return lines


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _help_text() -> str:
    return (
        "Send a Douyin share link or the full share text.\n"
        "The bot will download the video and run transcription automatically.\n"
        "Commands:\n"
        "/help - show this message\n"
        "/web - show the web UI URL if configured"
    )


def _build_failure_text(message: str, hint: Optional[str]) -> str:
    if not hint:
        return message
    return f"{message}\nHint: {hint}"


class TelegramProgressReporter:
    def __init__(
        self,
        client: TelegramBotClient,
        chat_id: int,
        *,
        enabled: bool,
    ) -> None:
        self._client = client
        self._chat_id = chat_id
        self._enabled = enabled
        self._last_phase: Optional[str] = None
        self._last_bucket = -1
        self._last_sent_at = 0.0

    def handle_manifest(self, manifest: dict[str, Any]) -> None:
        if not self._enabled:
            return

        status = str(manifest.get("status") or "")
        if status in {"success", "error"}:
            return

        phase = str(manifest.get("phase") or status or "")
        if phase != self._last_phase:
            self._last_phase = phase
            phase_message = _phase_progress_message(manifest)
            if phase_message:
                self._send(phase_message)

        if phase != "transcribing":
            return

        progress_percent = manifest.get("progress_percent")
        if progress_percent is None:
            return

        percent = float(progress_percent)
        bucket = int(percent // 20)
        now = monotonic()
        if bucket <= self._last_bucket:
            return
        if now - self._last_sent_at < 8:
            return

        self._last_bucket = bucket
        self._send(_transcribing_progress_message(manifest, percent))

    def _send(self, message: str) -> None:
        self._last_sent_at = monotonic()
        self._client.send_message(self._chat_id, message)


def _phase_progress_message(manifest: dict[str, Any]) -> Optional[str]:
    phase = str(manifest.get("phase") or "")
    job_id = str(manifest.get("job_id") or "-")

    mapping = {
        "queued": f"任务已排队。\njob_id: {job_id}",
        "downloading": f"开始下载视频。\njob_id: {job_id}",
        "extracting_audio": f"视频已下载，开始提取音频。\njob_id: {job_id}",
        "loading_model": f"音频已准备，开始加载转写模型。\njob_id: {job_id}",
        "writing_transcript": f"转写完成，正在写入文本文件。\njob_id: {job_id}",
    }
    return mapping.get(phase)


def _transcribing_progress_message(manifest: dict[str, Any], percent: float) -> str:
    job_id = str(manifest.get("job_id") or "-")
    processed = manifest.get("processed_seconds")
    duration = manifest.get("duration_seconds")
    eta = manifest.get("eta_seconds")
    parts = [f"转写进度 {int(percent)}%", f"job_id: {job_id}"]
    if processed is not None and duration:
        parts.append(f"已处理: {_format_clock(float(processed))} / {_format_clock(float(duration))}")
    if eta is not None and float(eta) > 0:
        parts.append(f"预计剩余: {_format_clock(float(eta))}")
    return "\n".join(parts)


def _format_clock(seconds: float) -> str:
    total_seconds = max(int(round(seconds)), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"
