from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
import logging
from pathlib import Path
from threading import Thread
from typing import Any, Optional
import time

from douyin_pipeline.config import Settings
from douyin_pipeline.jobs import sweep_stale_jobs
from douyin_pipeline.openclaw_api import OPENCLAW_TOKEN_HEADER, validate_openclaw_token
from douyin_pipeline.pipeline import run_prepared_job, transcribe_existing_job
from douyin_pipeline.telegram_manager import TelegramManager


STALE_SWEEP_INTERVAL_SECONDS = 30.0
logger = logging.getLogger(__name__)


def create_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app):
        stale_count = sweep_stale_jobs(settings.output_dir)
        manager = TelegramManager(settings)
        app.state.telegram_manager = manager
        app.state.last_stale_sweep_monotonic = time.monotonic()
        logger.info("web lifespan startup output_dir=%s stale_jobs_swept=%s", settings.output_dir, stale_count)
        manager.ensure_started_from_saved()
        try:
            yield
        finally:
            manager.stop()
            logger.info("web lifespan shutdown")

    return lifespan


def build_request_settings(base: Settings, payload: dict[str, Any]) -> Settings:
    cookies_value = str(payload.get("cookies", "")).strip()
    browser_value = str(payload.get("cookies_browser", "")).strip()
    model_value = str(payload.get("model", "")).strip()
    device_value = str(payload.get("device", "")).strip()
    language_value = str(payload.get("language", "")).strip()

    return replace(
        base,
        cookies_file=Path(cookies_value).expanduser().resolve() if cookies_value else base.cookies_file,
        cookies_from_browser=browser_value or base.cookies_from_browser,
        whisper_model=model_value or base.whisper_model,
        whisper_device=device_value or base.whisper_device,
        whisper_language=language_value or base.whisper_language,
    )


def validate_telegram_payload(manager: TelegramManager, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    enabled = bool(payload.get("enabled", False))
    clear_token = bool(payload.get("clear_token", False))
    supplied_token = str(payload.get("token", "") or "").strip()
    current_state = manager.get_public_state()
    has_saved_token = bool(current_state["config"].get("has_token"))
    will_have_token = (not clear_token) and bool(supplied_token or has_saved_token)

    if enabled and not will_have_token:
        return {
            "detail": "启用 Telegram 机器人前需要先配置 token。",
            "code": "telegram_token_missing",
            "hint": "先保存 token，再启动机器人。",
        }

    allowed_chat_ids = payload.get("allowed_chat_ids")
    if allowed_chat_ids is not None:
        try:
            values = [item.strip() for item in str(allowed_chat_ids).split(",") if item.strip()]
            for item in values:
                int(item)
        except ValueError:
            return {
                "detail": "允许访问的 chat id 格式不正确。",
                "code": "telegram_chat_ids_invalid",
                "hint": "多个 chat id 用英文逗号分隔。",
            }

    return None


def error_response(
    response_class,
    *,
    status_code: int,
    detail: str,
    code: str,
    hint: Optional[str] = None,
):
    return response_class(
        status_code=status_code,
        content={
            "detail": detail,
            "error_code": code,
            "error_hint": hint,
        },
    )


def openclaw_auth_error(response_class, request, settings: Settings):
    try:
        validate_openclaw_token(settings, request.headers.get(OPENCLAW_TOKEN_HEADER))
    except PermissionError:
        return error_response(
            response_class,
            status_code=401,
            detail="OpenClaw 访问令牌无效。",
            code="openclaw_auth_invalid",
            hint="检查 X-OpenClaw-Token 或 OPENCLAW_SHARED_TOKEN 配置。",
        )
    return None


async def maybe_sweep_stale_jobs(app, run_in_threadpool, *, force: bool = False) -> None:
    last_sweep = float(getattr(app.state, "last_stale_sweep_monotonic", 0.0) or 0.0)
    now = time.monotonic()
    if not force and (now - last_sweep) < STALE_SWEEP_INTERVAL_SECONDS:
        return

    swept = await run_in_threadpool(sweep_stale_jobs, app.state.settings.output_dir)
    app.state.last_stale_sweep_monotonic = now
    if swept:
        logger.warning("swept stale jobs count=%s", swept)


def run_job_in_background(prepared_job, settings: Settings) -> None:
    run_job_in_background_with_thread(prepared_job, settings, Thread)


def run_job_in_background_with_thread(prepared_job, settings: Settings, thread_class) -> None:
    thread = thread_class(
        target=_run_job_target,
        args=(prepared_job, settings),
        daemon=True,
    )
    thread.start()


def run_transcribe_in_background(job_dir: Path, settings: Settings) -> None:
    run_transcribe_in_background_with_thread(job_dir, settings, Thread)


def run_transcribe_in_background_with_thread(job_dir: Path, settings: Settings, thread_class) -> None:
    thread = thread_class(
        target=_run_transcribe_target,
        args=(job_dir, settings),
        daemon=True,
    )
    thread.start()


def _run_job_target(prepared_job, settings: Settings) -> None:
    try:
        run_prepared_job(prepared_job, settings)
    except Exception:
        logger.exception("background job failed job_id=%s", prepared_job.job_dir.name)


def _run_transcribe_target(job_dir: Path, settings: Settings) -> None:
    try:
        transcribe_existing_job(job_dir, settings)
    except Exception:
        logger.exception("background transcribe failed job_id=%s", job_dir.name)
