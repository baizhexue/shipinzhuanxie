from __future__ import annotations

import logging
from pathlib import Path
from threading import Thread
from typing import Any, Optional

try:
    from fastapi import Request
except ImportError:  # pragma: no cover - runtime dependency is optional for CLI-only use
    Request = Any

from douyin_pipeline import __version__
from douyin_pipeline.config import Settings, load_settings
from douyin_pipeline.doctor import has_failures, run_checks
from douyin_pipeline.errors import classify_exception
from douyin_pipeline.jobs import (
    ACTIVE_STATUSES,
    list_job_manifests,
    read_manifest,
    read_transcript_text,
    to_public_job,
)
from douyin_pipeline.logging_utils import configure_logging
from douyin_pipeline.openclaw_api import (
    build_openclaw_health_payload,
    build_openclaw_transcript_payload,
)
from douyin_pipeline.pipeline import (
    prepare_job,
    process_job,
)
from douyin_pipeline.runtime_config import (
    load_summary_prompt_config,
    summary_prompt_config_to_public_payload,
    update_summary_prompt_config,
)
from douyin_pipeline.web_jobs import (
    can_transcribe_manifest,
    delete_job_payload,
    get_job_manifest,
    get_job_transcript_payload,
    get_public_job,
    list_jobs_payload,
    queue_existing_transcribe,
)
from douyin_pipeline.web_support import (
    build_request_settings,
    create_lifespan,
    error_response,
    maybe_sweep_stale_jobs,
    openclaw_auth_error,
    run_job_in_background_with_thread,
    run_transcribe_in_background_with_thread,
    validate_telegram_payload,
)


ASSET_DIR = Path(__file__).with_name("web_assets")
STATIC_DIR = ASSET_DIR / "static"
INDEX_FILE = ASSET_DIR / "index.html"
logger = logging.getLogger(__name__)


def create_app(settings: Optional[Settings] = None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("Web UI requires `pip install -e .[web]`.") from exc

    resolved_settings = settings or load_settings()
    resolved_settings.output_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="视频转写助手", version=__version__, lifespan=create_lifespan(resolved_settings))
    app.state.settings = resolved_settings

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    app.mount("/output", StaticFiles(directory=resolved_settings.output_dir), name="output")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_FILE.read_text(encoding="utf-8")

    @app.get("/api/doctor")
    async def doctor(skip_asr: bool = False) -> dict[str, Any]:
        results = await run_in_threadpool(
            lambda: run_checks(app.state.settings, with_asr=not skip_asr)
        )
        return {
            "items": [
                {"name": item.name, "ok": item.ok, "detail": item.detail}
                for item in results
            ],
            "has_failures": has_failures(results),
        }

    @app.get("/api/jobs")
    async def jobs(
        offset: int = 0,
        limit: int = 20,
        q: str = "",
        status: Optional[str] = None,
        action: Optional[str] = None,
        active_only: bool = False,
    ) -> dict[str, Any]:
        await maybe_sweep_stale_jobs(app, run_in_threadpool)
        payload = await run_in_threadpool(
            lambda: list_jobs_payload(
                app.state.settings,
                offset=max(offset, 0),
                limit=limit,
                q=q,
                status=status,
                action=action,
                active_only=active_only,
            )
        )
        return payload

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        await maybe_sweep_stale_jobs(app, run_in_threadpool)
        payload = await run_in_threadpool(get_public_job, app.state.settings, job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return payload

    @app.get("/api/jobs/{job_id}/transcript")
    async def job_transcript(job_id: str) -> dict[str, Any]:
        await maybe_sweep_stale_jobs(app, run_in_threadpool)
        payload = await run_in_threadpool(get_job_transcript_payload, app.state.settings, job_id)
        if payload is None:
            return error_response(
                JSONResponse,
                status_code=404,
                detail="任务不存在。",
                code="job_not_found",
            )

        if not payload["transcript_text"]:
            return error_response(
                JSONResponse,
                status_code=404,
                detail="这条任务还没有转写文本。",
                code="transcript_missing",
                hint="先执行下载并转写，或对已下载任务补做转写。",
            )

        return payload

    @app.post("/api/jobs")
    async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        raw_input = str(payload.get("raw_input", "")).strip()
        action = str(payload.get("action", "download")).strip()

        if not raw_input:
            return error_response(
                JSONResponse,
                status_code=400,
                detail="请先粘贴分享文案或链接。",
                code="invalid_input",
                hint="支持完整分享文案、短链或直接 URL。",
            )
        if action not in {"download", "run"}:
            return error_response(
                JSONResponse,
                status_code=400,
                detail="当前只支持 download 和 run 两种任务模式。",
                code="invalid_action",
            )

        request_settings = build_request_settings(app.state.settings, payload)

        try:
            prepared_job = prepare_job(raw_input, request_settings, action)
        except ValueError as exc:
            error_info = classify_exception(exc)
            return error_response(
                JSONResponse,
                status_code=400,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )

        _run_job_in_background(prepared_job, request_settings)

        manifest = await run_in_threadpool(get_public_job, request_settings, prepared_job.job_dir.name)
        if manifest is None:
            raise HTTPException(status_code=500, detail="Job manifest was not created.")

        return manifest

    @app.post("/api/jobs/{job_id}/transcribe")
    async def transcribe_job(job_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload = payload or {}
        request_settings = build_request_settings(app.state.settings, payload)
        manifest = await run_in_threadpool(get_job_manifest, app.state.settings, job_id)
        if manifest is None:
            return error_response(
                JSONResponse,
                status_code=404,
                detail="任务不存在。",
                code="job_not_found",
                hint="刷新历史记录后再试。",
            )
        if manifest.get("status") in ACTIVE_STATUSES:
            return error_response(
                JSONResponse,
                status_code=409,
                detail="任务仍在执行中，暂时不能重复转写。",
                code="job_running",
            )
        if not manifest.get("video_path"):
            return error_response(
                JSONResponse,
                status_code=400,
                detail="这条任务没有可转写的视频文件。",
                code="video_missing_for_transcribe",
                hint="请先完成视频下载。",
            )
        if not can_transcribe_manifest(manifest):
            return to_public_job(manifest)

        refreshed = await run_in_threadpool(queue_existing_transcribe, request_settings, job_id)
        if refreshed is None:
            raise HTTPException(status_code=500, detail="Job manifest was not updated.")

        _run_transcribe_in_background(request_settings.output_dir / job_id, request_settings)
        return refreshed

    @app.get("/api/openclaw/health")
    async def openclaw_health(request: Request):
        auth_error = openclaw_auth_error(JSONResponse, request, app.state.settings)
        if auth_error is not None:
            return auth_error
        return build_openclaw_health_payload(app.state.settings)

    @app.post("/api/openclaw/transcribe")
    async def openclaw_transcribe(request: Request, payload: dict[str, Any]):
        auth_error = openclaw_auth_error(JSONResponse, request, app.state.settings)
        if auth_error is not None:
            return auth_error

        raw_input = str(payload.get("raw_input", "")).strip()
        if not raw_input:
            return error_response(
                JSONResponse,
                status_code=400,
                detail="请先提供要转写的视频链接或完整分享文案。",
                code="invalid_input",
                hint="支持抖音、Bilibili、小红书、快手和 YouTube。",
            )

        request_settings = build_request_settings(app.state.settings, payload)

        try:
            manifest = await run_in_threadpool(
                process_job,
                raw_input,
                request_settings,
                "run",
            )
            return build_openclaw_transcript_payload(request_settings, manifest)
        except ValueError as exc:
            error_info = classify_exception(exc)
            return error_response(
                JSONResponse,
                status_code=400,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )
        except Exception as exc:
            error_info = classify_exception(exc)
            return error_response(
                JSONResponse,
                status_code=500,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )

    @app.delete("/api/jobs/{job_id}")
    async def remove_job(job_id: str):
        await maybe_sweep_stale_jobs(app, run_in_threadpool)
        try:
            return await run_in_threadpool(delete_job_payload, app.state.settings, job_id)
        except ValueError as exc:
            message = str(exc)
            if message == "Job not found.":
                return error_response(
                    JSONResponse,
                    status_code=404,
                    detail="任务不存在。",
                    code="job_not_found",
                )
            if message == "Running jobs cannot be deleted.":
                return error_response(
                    JSONResponse,
                    status_code=409,
                    detail="运行中的任务不能删除。",
                    code="job_running",
                    hint="请等任务结束后再删除。",
                )
            return error_response(
                JSONResponse,
                status_code=400,
                detail=message,
                code="job_delete_failed",
            )

    @app.get("/api/settings/telegram")
    async def telegram_settings() -> dict[str, Any]:
        return await run_in_threadpool(app.state.telegram_manager.get_public_state)

    @app.get("/api/settings/summary-prompts")
    async def summary_prompt_settings() -> dict[str, Any]:
        config = await run_in_threadpool(load_summary_prompt_config, app.state.settings.output_dir)
        return summary_prompt_config_to_public_payload(config)

    @app.put("/api/settings/summary-prompts")
    async def save_summary_prompt_settings(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            config = await run_in_threadpool(
                update_summary_prompt_config,
                app.state.settings.output_dir,
                payload,
            )
            return summary_prompt_config_to_public_payload(config)
        except ValueError as exc:
            return error_response(
                JSONResponse,
                status_code=400,
                detail=str(exc),
                code="summary_prompt_invalid",
            )
        except Exception as exc:
            return error_response(
                JSONResponse,
                status_code=500,
                detail="总结提示词保存失败。",
                code="summary_prompt_save_failed",
                hint=str(exc),
            )

    @app.put("/api/settings/telegram")
    async def save_telegram_settings(payload: dict[str, Any]) -> dict[str, Any]:
        validation_error = validate_telegram_payload(app.state.telegram_manager, payload)
        if validation_error is not None:
            return error_response(JSONResponse, status_code=400, **validation_error)

        try:
            return await run_in_threadpool(app.state.telegram_manager.save_config, payload)
        except ValueError as exc:
            return error_response(
                JSONResponse,
                status_code=400,
                detail=str(exc),
                code="telegram_config_invalid",
            )
        except Exception as exc:
            return error_response(
                JSONResponse,
                status_code=500,
                detail="Telegram 配置保存失败。",
                code="telegram_config_failed",
                hint=str(exc),
            )

    @app.post("/api/settings/telegram/start")
    async def start_telegram(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        requested_payload = dict(payload or {})
        requested_payload["enabled"] = True
        validation_error = validate_telegram_payload(app.state.telegram_manager, requested_payload)
        if validation_error is not None:
            return error_response(JSONResponse, status_code=400, **validation_error)

        try:
            return await run_in_threadpool(app.state.telegram_manager.save_config, requested_payload)
        except Exception as exc:
            return error_response(
                JSONResponse,
                status_code=500,
                detail="Telegram 机器人启动失败。",
                code="telegram_start_failed",
                hint=str(exc),
            )

    @app.post("/api/settings/telegram/stop")
    async def stop_telegram() -> dict[str, Any]:
        try:
            return await run_in_threadpool(
                app.state.telegram_manager.save_config,
                {"enabled": False},
            )
        except Exception as exc:
            return error_response(
                JSONResponse,
                status_code=500,
                detail="Telegram 机器人停止失败。",
                code="telegram_stop_failed",
                hint=str(exc),
            )

    return app


def start_server(settings: Settings, *, host: str = "127.0.0.1", port: int = 4444) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Web server requires `pip install -e .[web]`.") from exc

    log_file = configure_logging(settings.output_dir, service_name="web")
    logger.info("starting web server host=%s port=%s output_dir=%s log_file=%s", host, port, settings.output_dir, log_file)
    uvicorn.run(create_app(settings), host=host, port=port)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Start the video transcription web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", default=4444, type=int, help="bind port")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--cookies", default=None, help="cookies.txt path")
    parser.add_argument("--model", default=None, help="whisper model name")
    parser.add_argument("--device", default=None, help="whisper device")
    parser.add_argument("--language", default=None, help="whisper language hint")
    args = parser.parse_args()

    settings = load_settings(
        output_dir=args.out,
        cookies_file=args.cookies,
        whisper_model=args.model,
        whisper_device=args.device,
        whisper_language=args.language,
    )
    start_server(settings, host=args.host, port=args.port)
    return 0


def _run_job_in_background(prepared_job, settings: Settings) -> None:
    run_job_in_background_with_thread(prepared_job, settings, Thread)


def _run_transcribe_in_background(job_dir: Path, settings: Settings) -> None:
    run_transcribe_in_background_with_thread(job_dir, settings, Thread)
