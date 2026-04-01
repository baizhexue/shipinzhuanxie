from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
from threading import Thread
from time import monotonic, sleep, time
from typing import Any, Iterable, Optional
import json
import mimetypes
import uuid
import urllib.error
import urllib.request

from douyin_pipeline.config import Settings
from douyin_pipeline.deepseek_summary import (
    SUMMARY_STYLE_LABELS,
    SummaryError,
    summarize_to_file,
)
from douyin_pipeline.errors import classify_exception
from douyin_pipeline.jobs import read_manifest, read_transcript_text, to_public_job, write_manifest
from douyin_pipeline.logging_utils import configure_logging
from douyin_pipeline.parser import extract_share_url
from douyin_pipeline.pipeline import prepare_job, run_prepared_job
from douyin_pipeline.telegram_messages import (
    DEFAULT_MESSAGE_LIMIT,
    DEFAULT_TRANSCRIPT_PREVIEW_LIMIT,
    build_summary_document_caption,
    build_summary_expired_text,
    build_summary_failed_text,
    build_summary_selection_text,
    build_summary_skipped_text,
    build_summary_started_text,
    build_document_send_failed_text,
    build_failure_manifest_text,
    build_failure_text,
    build_help_text,
    build_job_started_text,
    build_job_received_text,
    build_mode_expired_text,
    build_mode_selection_text,
    build_success_summary_text,
    build_transcript_caption,
    build_web_missing_text,
    phase_progress_message,
    resolve_transcript_file,
    split_message_chunks,
    transcribing_progress_message,
    truncate_text,
)


DEFAULT_ALLOWED_UPDATES = ("message", "callback_query")
DEFAULT_POLL_TIMEOUT = 25
DEFAULT_RETRY_DELAY = 3.0
MODE_CALLBACK_PREFIX = "txmode:"
SUMMARY_CALLBACK_PREFIX = "txsummary:"
MAX_PENDING_SELECTIONS = 20
logger = logging.getLogger(__name__)


MODE_PRESETS = {
    "fast": {
        "label": "快速转写",
        "action": "run",
        "whisper_model": "large-v3-turbo",
        "whisper_language": "zh",
        "whisper_beam_size": 3,
    },
    "accurate": {
        "label": "高精度转写",
        "action": "run",
        "whisper_model": "large-v3",
        "whisper_language": "zh",
        "whisper_beam_size": 5,
    },
    "download": {
        "label": "只下载视频",
        "action": "download",
    },
}


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
    configure_logging(app_settings.output_dir, service_name="telegram")
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
    parser.add_argument("--language", default=None, help="whisper language hint")
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
        whisper_language=args.language,
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
        logger.info(
            "telegram bot ready username=%s allowed_chats=%s",
            bot_profile.get("username", "unknown"),
            self._bot_settings.allowed_chat_ids or "all",
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
                logger.warning("telegram bot poll error: %s", exc)
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
        callback_query = update.get("callback_query")
        if isinstance(callback_query, dict):
            self._handle_callback_query(callback_query)
            return

        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat") or {}
        chat_id = int(chat.get("id"))
        text = _extract_message_text(message)

        if self._bot_settings.allowed_chat_ids and chat_id not in self._bot_settings.allowed_chat_ids:
            logger.info("telegram bot ignored unauthorized chat_id=%s", chat_id)
            return

        if not text:
            self._client.send_message(chat_id, build_help_text())
            return

        normalized = text.strip()
        if normalized in {"/start", "/help"}:
            self._client.send_message(chat_id, build_help_text())
            return

        if normalized == "/web":
            if not self._bot_settings.public_base_url:
                self._client.send_message(chat_id, build_web_missing_text())
                return
            self._client.send_message(chat_id, self._bot_settings.public_base_url)
            return

        try:
            extract_share_url(normalized)
        except ValueError:
            self._client.send_message(chat_id, build_help_text())
            return

        request_id = self._create_pending_request(chat_id, normalized)
        self._client.send_message(
            chat_id,
            build_mode_selection_text(),
            reply_markup=_build_mode_selection_markup(request_id),
        )

    def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_id = str(callback_query.get("id") or "")
        data = str(callback_query.get("data") or "")
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        from_user = callback_query.get("from") or {}
        chat_id = int(chat.get("id") or from_user.get("id") or 0)

        if self._bot_settings.allowed_chat_ids and chat_id not in self._bot_settings.allowed_chat_ids:
            logger.info("telegram bot ignored unauthorized callback chat_id=%s", chat_id)
            if callback_id:
                self._client.answer_callback_query(callback_id, text="当前会话未授权。", show_alert=False)
            return

        mode_selection = _parse_mode_callback_data(data)
        if mode_selection is not None:
            self._handle_mode_callback(
                callback_query,
                callback_id=callback_id,
                chat_id=chat_id,
                selection=mode_selection,
            )
            return

        summary_selection = _parse_summary_callback_data(data)
        if summary_selection is not None:
            self._handle_summary_callback(
                callback_query,
                callback_id=callback_id,
                chat_id=chat_id,
                selection=summary_selection,
            )
            return

        if callback_id:
            self._client.answer_callback_query(callback_id, text="无效选择。", show_alert=False)

    def _handle_mode_callback(
        self,
        callback_query: dict[str, Any],
        *,
        callback_id: str,
        chat_id: int,
        selection: tuple[str, str],
    ) -> None:
        message = callback_query.get("message") or {}
        request_id, mode = selection
        pending_request = self._pop_pending_request(request_id)
        if pending_request is None or int(pending_request.get("chat_id") or 0) != chat_id:
            if callback_id:
                self._client.answer_callback_query(callback_id, text=build_mode_expired_text(), show_alert=False)
            return

        if callback_id:
            if mode == "cancel":
                self._client.answer_callback_query(callback_id, text="已取消。", show_alert=False)
            else:
                self._client.answer_callback_query(
                    callback_id,
                    text=f"已选择{MODE_PRESETS[mode]['label']}",
                    show_alert=False,
                )

        self._clear_callback_markup(chat_id, message)

        if mode == "cancel":
            self._client.send_message(chat_id, "这条任务已取消。")
            return

        thread = Thread(
            target=self._process_message_job,
            args=(chat_id, str(pending_request["raw_input"]), mode),
            daemon=True,
        )
        thread.start()

    def _handle_summary_callback(
        self,
        callback_query: dict[str, Any],
        *,
        callback_id: str,
        chat_id: int,
        selection: tuple[str, str],
    ) -> None:
        message = callback_query.get("message") or {}
        request_id, style = selection
        pending_summary = self._pop_pending_summary(request_id)
        if pending_summary is None or int(pending_summary.get("chat_id") or 0) != chat_id:
            if callback_id:
                self._client.answer_callback_query(callback_id, text=build_summary_expired_text(), show_alert=False)
            return

        if callback_id:
            if style == "skip":
                self._client.answer_callback_query(callback_id, text="已跳过总结。", show_alert=False)
            else:
                self._client.answer_callback_query(
                    callback_id,
                    text=f"已选择{SUMMARY_STYLE_LABELS[style]}总结",
                    show_alert=False,
                )

        self._clear_callback_markup(chat_id, message)

        job_id = str(pending_summary["job_id"])
        if style == "skip":
            self._client.send_message(chat_id, build_summary_skipped_text(job_id))
            return

        thread = Thread(
            target=self._process_summary_job,
            args=(chat_id, job_id, style),
            daemon=True,
        )
        thread.start()

    def _process_message_job(self, chat_id: int, raw_input: str, mode: str) -> None:
        logger.info("telegram bot received job chat_id=%s mode=%s", chat_id, mode)
        resolved_settings, action, mode_label = _resolve_mode_settings(self._app_settings, mode)
        try:
            prepared_job = prepare_job(raw_input, resolved_settings, action=action)
        except Exception as exc:
            error_info = classify_exception(exc)
            logger.exception("telegram bot failed to prepare job chat_id=%s", chat_id)
            self._client.send_message(chat_id, build_failure_text(error_info.message, error_info.hint))
            return

        self._client.send_message(
            chat_id,
            build_job_started_text(prepared_job.job_dir.name, mode_label=mode_label, action=action),
        )
        progress_reporter = TelegramProgressReporter(
            self._client,
            chat_id,
            enabled=self._bot_settings.progress_updates,
        )

        try:
            manifest = run_prepared_job(
                prepared_job,
                resolved_settings,
                status_callback=progress_reporter.handle_manifest,
            )
        except Exception as exc:
            logger.exception("telegram bot job failed chat_id=%s job_id=%s", chat_id, prepared_job.job_dir.name)
            failed_manifest = read_manifest(prepared_job.job_dir) or {
                "job_id": prepared_job.job_dir.name,
                "error": str(exc),
            }
            self._send_failure(chat_id, failed_manifest)
            return

        logger.info("telegram bot job completed chat_id=%s job_id=%s", chat_id, prepared_job.job_dir.name)
        self._send_success(chat_id, manifest)

    def _send_failure(self, chat_id: int, manifest: dict[str, Any]) -> None:
        self._client.send_message(chat_id, build_failure_manifest_text(manifest))

    def _send_success(self, chat_id: int, manifest: dict[str, Any]) -> None:
        public_job = to_public_job(manifest)
        transcript_preview = manifest.get("transcript_preview") or ""
        self._client.send_message(
            chat_id,
            build_success_summary_text(public_job, self._bot_settings.public_base_url),
        )

        if transcript_preview:
            self._client.send_message(
                chat_id,
                truncate_text(transcript_preview, DEFAULT_TRANSCRIPT_PREVIEW_LIMIT),
            )

        absolute_transcript_path = resolve_transcript_file(
            self._app_settings.output_dir,
            manifest.get("transcript_path"),
        )
        if absolute_transcript_path is not None:
            caption = build_transcript_caption(str(public_job.get("job_id", "-")))
            try:
                self._client.send_document(chat_id, absolute_transcript_path, caption=caption)
            except Exception as exc:
                self._client.send_message(chat_id, build_document_send_failed_text(exc))

        if absolute_transcript_path is not None and self._app_settings.deepseek_api_key:
            summary_request_id = self._create_pending_summary(chat_id, str(public_job.get("job_id", "-")))
            self._client.send_message(
                chat_id,
                build_summary_selection_text(str(public_job.get("job_id", "-"))),
                reply_markup=_build_summary_selection_markup(summary_request_id),
            )

    def _process_summary_job(self, chat_id: int, job_id: str, style: str) -> None:
        style_label = SUMMARY_STYLE_LABELS[style]
        logger.info("telegram summary started chat_id=%s job_id=%s style=%s", chat_id, job_id, style)
        self._client.send_message(chat_id, build_summary_started_text(job_id, style_label))

        job_dir = self._app_settings.output_dir / job_id
        manifest = read_manifest(job_dir)
        if manifest is None:
            self._client.send_message(chat_id, build_summary_failed_text(style_label, "任务记录不存在。"))
            return

        transcript_text = read_transcript_text(self._app_settings.output_dir, manifest)
        if not transcript_text:
            self._client.send_message(chat_id, build_summary_failed_text(style_label, "转写文本不存在。"))
            return

        self._write_summary_status(job_id, status="running", style=style)

        try:
            summary_result = summarize_to_file(
                transcript_text,
                style=style,
                job_dir=job_dir,
                settings=self._app_settings,
            )
        except Exception as exc:
            logger.exception("telegram summary failed chat_id=%s job_id=%s style=%s", chat_id, job_id, style)
            self._write_summary_status(job_id, status="error", style=style, error=str(exc))
            message = str(exc)
            if isinstance(exc, SummaryError) and not message:
                message = "DeepSeek 总结失败。"
            self._client.send_message(chat_id, build_summary_failed_text(style_label, message))
            return

        updated_manifest = self._write_summary_status(
            job_id,
            status="success",
            style=style,
            summary_path=summary_result.summary_path,
            summary_text=summary_result.text,
            error=None,
        )
        public_job = to_public_job(updated_manifest)
        if self._bot_settings.public_base_url:
            summary_links = [
                line for line in build_success_summary_text(public_job, self._bot_settings.public_base_url).splitlines()
                if line.startswith("总结:")
            ]
            if summary_links:
                self._client.send_message(chat_id, "\n".join(summary_links))

        for chunk in split_message_chunks(summary_result.text):
            self._client.send_message(chat_id, chunk)

        try:
            self._client.send_document(
                chat_id,
                summary_result.summary_path,
                caption=build_summary_document_caption(job_id, style_label),
            )
        except Exception as exc:
            self._client.send_message(chat_id, build_document_send_failed_text(exc))

    def _clear_callback_markup(self, chat_id: int, message: dict[str, Any]) -> None:
        message_id = message.get("message_id")
        if message_id is None:
            return
        try:
            self._client.edit_message_reply_markup(chat_id, int(message_id), reply_markup=None)
        except Exception:
            logger.exception("telegram bot failed to clear selection markup chat_id=%s", chat_id)

    def _create_pending_request(self, chat_id: int, raw_input: str) -> str:
        pending_requests = dict(self._state.get("pending_requests") or {})
        pending_requests = _prune_pending_requests(pending_requests)
        request_id = uuid.uuid4().hex[:10]
        pending_requests[request_id] = {
            "chat_id": chat_id,
            "raw_input": raw_input,
            "created_at": time(),
        }
        self._state["pending_requests"] = pending_requests
        _save_state(self._bot_settings.state_path, self._state)
        return request_id

    def _pop_pending_request(self, request_id: str) -> Optional[dict[str, Any]]:
        pending_requests = dict(self._state.get("pending_requests") or {})
        pending_request = pending_requests.pop(request_id, None)
        self._state["pending_requests"] = pending_requests
        _save_state(self._bot_settings.state_path, self._state)
        return pending_request

    def _create_pending_summary(self, chat_id: int, job_id: str) -> str:
        pending_summaries = dict(self._state.get("pending_summaries") or {})
        pending_summaries = _prune_pending_summaries(pending_summaries)
        request_id = uuid.uuid4().hex[:10]
        pending_summaries[request_id] = {
            "chat_id": chat_id,
            "job_id": job_id,
            "created_at": time(),
        }
        self._state["pending_summaries"] = pending_summaries
        _save_state(self._bot_settings.state_path, self._state)
        return request_id

    def _pop_pending_summary(self, request_id: str) -> Optional[dict[str, Any]]:
        pending_summaries = dict(self._state.get("pending_summaries") or {})
        pending_summary = pending_summaries.pop(request_id, None)
        self._state["pending_summaries"] = pending_summaries
        _save_state(self._bot_settings.state_path, self._state)
        return pending_summary

    def _write_summary_status(
        self,
        job_id: str,
        *,
        status: str,
        style: str,
        summary_path: Optional[Path] = None,
        summary_text: Optional[str] = None,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        job_dir = self._app_settings.output_dir / job_id
        manifest = read_manifest(job_dir)
        if manifest is None:
            raise ValueError("Job manifest not found.")

        manifest["summary_status"] = status
        manifest["summary_style"] = style
        manifest["summary_error"] = error
        if summary_path is not None:
            manifest["summary_path"] = str(summary_path.relative_to(self._app_settings.output_dir))
        if summary_text is not None:
            manifest["summary_preview"] = truncate_text(summary_text, 800)
        write_manifest(job_dir, manifest)
        return manifest


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

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        safe_text = truncate_text(text, DEFAULT_MESSAGE_LIMIT)
        payload = {
            "chat_id": chat_id,
            "text": safe_text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._json_request("sendMessage", payload=payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = truncate_text(text, 180)
        return self._json_request("answerCallbackQuery", payload=payload)

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        *,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._json_request("editMessageReplyMarkup", payload=payload)

    def send_document(
        self,
        chat_id: int,
        document_path: Path,
        *,
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = truncate_text(caption, 900)
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
        return {"offset": None, "pending_requests": {}, "pending_summaries": {}}

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"offset": None, "pending_requests": {}, "pending_summaries": {}}

    if not isinstance(payload, dict):
        return {"offset": None, "pending_requests": {}, "pending_summaries": {}}

    pending_requests = payload.get("pending_requests")
    if not isinstance(pending_requests, dict):
        pending_requests = {}
    pending_summaries = payload.get("pending_summaries")
    if not isinstance(pending_summaries, dict):
        pending_summaries = {}
    return {
        "offset": payload.get("offset"),
        "pending_requests": _prune_pending_requests(pending_requests),
        "pending_summaries": _prune_pending_summaries(pending_summaries),
    }


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


def _build_mode_selection_markup(request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "快速转写", "callback_data": f"{MODE_CALLBACK_PREFIX}fast:{request_id}"},
                {"text": "高精度转写", "callback_data": f"{MODE_CALLBACK_PREFIX}accurate:{request_id}"},
            ],
            [
                {"text": "只下载视频", "callback_data": f"{MODE_CALLBACK_PREFIX}download:{request_id}"},
                {"text": "取消", "callback_data": f"{MODE_CALLBACK_PREFIX}cancel:{request_id}"},
            ],
        ]
    }


def _build_summary_selection_markup(request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "通用", "callback_data": f"{SUMMARY_CALLBACK_PREFIX}general:{request_id}"},
                {"text": "大白话", "callback_data": f"{SUMMARY_CALLBACK_PREFIX}plain:{request_id}"},
                {"text": "知识型", "callback_data": f"{SUMMARY_CALLBACK_PREFIX}knowledge:{request_id}"},
            ],
            [
                {"text": "跳过总结", "callback_data": f"{SUMMARY_CALLBACK_PREFIX}skip:{request_id}"},
            ],
        ]
    }


def _parse_mode_callback_data(data: str) -> Optional[tuple[str, str]]:
    if not data.startswith(MODE_CALLBACK_PREFIX):
        return None
    payload = data[len(MODE_CALLBACK_PREFIX):]
    mode, separator, request_id = payload.partition(":")
    if not separator or not request_id:
        return None
    if mode not in {*MODE_PRESETS.keys(), "cancel"}:
        return None
    return request_id, mode


def _parse_summary_callback_data(data: str) -> Optional[tuple[str, str]]:
    if not data.startswith(SUMMARY_CALLBACK_PREFIX):
        return None
    payload = data[len(SUMMARY_CALLBACK_PREFIX):]
    style, separator, request_id = payload.partition(":")
    if not separator or not request_id:
        return None
    if style not in {*SUMMARY_STYLE_LABELS.keys(), "skip"}:
        return None
    return request_id, style


def _prune_pending_requests(pending_requests: dict[str, Any]) -> dict[str, Any]:
    normalized_items: list[tuple[str, dict[str, Any]]] = []
    for request_id, payload in pending_requests.items():
        if not isinstance(payload, dict):
            continue
        raw_input = str(payload.get("raw_input") or "").strip()
        chat_id = payload.get("chat_id")
        created_at = float(payload.get("created_at") or 0.0)
        if not raw_input or not chat_id:
            continue
        normalized_items.append(
            (
                str(request_id),
                {
                    "chat_id": int(chat_id),
                    "raw_input": raw_input,
                    "created_at": created_at,
                },
            )
        )

    normalized_items.sort(key=lambda item: item[1]["created_at"], reverse=True)
    return dict(normalized_items[:MAX_PENDING_SELECTIONS])


def _prune_pending_summaries(pending_summaries: dict[str, Any]) -> dict[str, Any]:
    normalized_items: list[tuple[str, dict[str, Any]]] = []
    for request_id, payload in pending_summaries.items():
        if not isinstance(payload, dict):
            continue
        job_id = str(payload.get("job_id") or "").strip()
        chat_id = payload.get("chat_id")
        created_at = float(payload.get("created_at") or 0.0)
        if not job_id or not chat_id:
            continue
        normalized_items.append(
            (
                str(request_id),
                {
                    "chat_id": int(chat_id),
                    "job_id": job_id,
                    "created_at": created_at,
                },
            )
        )

    normalized_items.sort(key=lambda item: item[1]["created_at"], reverse=True)
    return dict(normalized_items[:MAX_PENDING_SELECTIONS])


def _resolve_mode_settings(base_settings: Settings, mode: str) -> tuple[Settings, str, str]:
    preset = MODE_PRESETS[mode]
    action = str(preset["action"])
    label = str(preset["label"])
    if action == "download":
        return base_settings, action, label

    return (
        replace(
            base_settings,
            whisper_model=str(preset["whisper_model"]),
            whisper_language=str(preset["whisper_language"]),
            whisper_beam_size=int(preset["whisper_beam_size"]),
        ),
        action,
        label,
    )

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
            phase_message = phase_progress_message(manifest)
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
        self._send(transcribing_progress_message(manifest, percent))

    def _send(self, message: str) -> None:
        self._last_sent_at = monotonic()
        self._client.send_message(self._chat_id, message)

