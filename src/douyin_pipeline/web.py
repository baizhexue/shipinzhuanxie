from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
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
    delete_job,
    list_job_manifests,
    read_manifest,
    read_transcript_text,
    to_public_job,
    write_manifest,
)
from douyin_pipeline.openclaw_api import (
    OPENCLAW_TOKEN_HEADER,
    build_openclaw_health_payload,
    build_openclaw_transcript_payload,
    validate_openclaw_token,
)
from douyin_pipeline.pipeline import (
    prepare_job,
    process_job,
    run_prepared_job,
    transcribe_existing_job,
)
from douyin_pipeline.telegram_manager import TelegramManager


ASSET_DIR = Path(__file__).with_name("web_assets")
STATIC_DIR = ASSET_DIR / "static"
INDEX_FILE = ASSET_DIR / "index.html"


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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = TelegramManager(resolved_settings)
        app.state.telegram_manager = manager
        manager.ensure_started_from_saved()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="视频转写助手", version=__version__, lifespan=lifespan)
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
        safe_limit = max(1, min(limit, 50))
        payload = await run_in_threadpool(
            lambda: list_job_manifests(
                app.state.settings.output_dir,
                offset=max(offset, 0),
                limit=safe_limit,
                q=q,
                status=status,
                action=action,
                active_only=active_only,
            )
        )
        return {
            "jobs": [to_public_job(manifest) for manifest in payload["items"]],
            "offset": payload["offset"],
            "limit": payload["limit"],
            "filtered_total": payload["filtered_total"],
            "total_jobs": payload["total_jobs"],
            "has_more": payload["has_more"],
            "summary": payload["summary"],
        }

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        manifest = await run_in_threadpool(
            read_manifest,
            app.state.settings.output_dir / job_id,
        )
        if manifest is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return to_public_job(manifest)

    @app.get("/api/jobs/{job_id}/transcript")
    async def job_transcript(job_id: str) -> dict[str, Any]:
        manifest = await run_in_threadpool(
            read_manifest,
            app.state.settings.output_dir / job_id,
        )
        if manifest is None:
            return _error_response(
                JSONResponse,
                status_code=404,
                detail="任务不存在。",
                code="job_not_found",
            )

        transcript_text = await run_in_threadpool(
            read_transcript_text,
            app.state.settings.output_dir,
            manifest,
        )
        if not transcript_text:
            return _error_response(
                JSONResponse,
                status_code=404,
                detail="这条任务还没有转写文本。",
                code="transcript_missing",
                hint="先执行下载并转写，或对已下载任务补做转写。",
            )

        return {
            "job": to_public_job(manifest),
            "transcript_text": transcript_text,
            "transcript_char_count": len(transcript_text),
        }

    @app.post("/api/jobs")
    async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        raw_input = str(payload.get("raw_input", "")).strip()
        action = str(payload.get("action", "download")).strip()

        if not raw_input:
            return _error_response(
                JSONResponse,
                status_code=400,
                detail="请先粘贴分享文案或链接。",
                code="invalid_input",
                hint="支持完整分享文案、短链或直接 URL。",
            )
        if action not in {"download", "run"}:
            return _error_response(
                JSONResponse,
                status_code=400,
                detail="当前只支持 download 和 run 两种任务模式。",
                code="invalid_action",
            )

        request_settings = _build_request_settings(app.state.settings, payload)

        try:
            prepared_job = prepare_job(raw_input, request_settings, action)
        except ValueError as exc:
            error_info = classify_exception(exc)
            return _error_response(
                JSONResponse,
                status_code=400,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )

        thread = Thread(
            target=_run_job_in_background,
            args=(prepared_job, request_settings),
            daemon=True,
        )
        thread.start()

        manifest = read_manifest(prepared_job.job_dir)
        if manifest is None:
            raise HTTPException(status_code=500, detail="Job manifest was not created.")

        return to_public_job(manifest)

    @app.post("/api/jobs/{job_id}/transcribe")
    async def transcribe_job(job_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload = payload or {}
        request_settings = _build_request_settings(app.state.settings, payload)
        job_dir = app.state.settings.output_dir / job_id
        manifest = read_manifest(job_dir)
        if manifest is None:
            return _error_response(
                JSONResponse,
                status_code=404,
                detail="任务不存在。",
                code="job_not_found",
                hint="刷新历史记录后再试。",
            )
        if manifest.get("status") in ACTIVE_STATUSES:
            return _error_response(
                JSONResponse,
                status_code=409,
                detail="任务仍在执行中，暂时不能重复转写。",
                code="job_running",
            )
        if not manifest.get("video_path"):
            return _error_response(
                JSONResponse,
                status_code=400,
                detail="这条任务没有可转写的视频文件。",
                code="video_missing_for_transcribe",
                hint="请先完成视频下载。",
            )
        if manifest.get("transcript_path"):
            return to_public_job(manifest)

        queued_manifest = dict(manifest)
        queued_manifest.update(
            {
                "status": "transcribing",
                "detail": "Preparing transcript for existing video.",
                "phase": "extracting_audio",
                "progress_percent": 34.0,
                "eta_seconds": None,
                "processed_seconds": 0.0,
                "duration_seconds": None,
                "error": None,
                "error_code": None,
                "error_kind": None,
                "error_hint": None,
                "technical_error": None,
            }
        )
        write_manifest(job_dir, queued_manifest)

        thread = Thread(
            target=_run_transcribe_in_background,
            args=(job_dir, request_settings),
            daemon=True,
        )
        thread.start()

        refreshed = read_manifest(job_dir)
        if refreshed is None:
            raise HTTPException(status_code=500, detail="Job manifest was not updated.")
        return to_public_job(refreshed)

    @app.get("/api/openclaw/health")
    async def openclaw_health(request: Request):
        auth_error = _openclaw_auth_error(JSONResponse, request, app.state.settings)
        if auth_error is not None:
            return auth_error
        return build_openclaw_health_payload(app.state.settings)

    @app.post("/api/openclaw/transcribe")
    async def openclaw_transcribe(request: Request, payload: dict[str, Any]):
        auth_error = _openclaw_auth_error(JSONResponse, request, app.state.settings)
        if auth_error is not None:
            return auth_error

        raw_input = str(payload.get("raw_input", "")).strip()
        if not raw_input:
            return _error_response(
                JSONResponse,
                status_code=400,
                detail="请先提供要转写的视频链接或完整分享文案。",
                code="invalid_input",
                hint="支持抖音、Bilibili、小红书、快手和 YouTube。",
            )

        request_settings = _build_request_settings(app.state.settings, payload)

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
            return _error_response(
                JSONResponse,
                status_code=400,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )
        except Exception as exc:
            error_info = classify_exception(exc)
            return _error_response(
                JSONResponse,
                status_code=500,
                detail=error_info.message,
                code=error_info.code,
                hint=error_info.hint,
            )

    @app.delete("/api/jobs/{job_id}")
    async def remove_job(job_id: str):
        try:
            deleted = await run_in_threadpool(delete_job, app.state.settings.output_dir, job_id)
        except ValueError as exc:
            message = str(exc)
            if message == "Job not found.":
                return _error_response(
                    JSONResponse,
                    status_code=404,
                    detail="任务不存在。",
                    code="job_not_found",
                )
            if message == "Running jobs cannot be deleted.":
                return _error_response(
                    JSONResponse,
                    status_code=409,
                    detail="运行中的任务不能删除。",
                    code="job_running",
                    hint="请等任务结束后再删除。",
                )
            return _error_response(
                JSONResponse,
                status_code=400,
                detail=message,
                code="job_delete_failed",
            )

        return {
            "deleted_job": to_public_job(deleted),
            "message": "任务已删除。",
        }

    @app.get("/api/settings/telegram")
    async def telegram_settings() -> dict[str, Any]:
        return await run_in_threadpool(app.state.telegram_manager.get_public_state)

    @app.put("/api/settings/telegram")
    async def save_telegram_settings(payload: dict[str, Any]) -> dict[str, Any]:
        validation_error = _validate_telegram_payload(app.state.telegram_manager, payload)
        if validation_error is not None:
            return _error_response(JSONResponse, status_code=400, **validation_error)

        try:
            return await run_in_threadpool(app.state.telegram_manager.save_config, payload)
        except ValueError as exc:
            return _error_response(
                JSONResponse,
                status_code=400,
                detail=str(exc),
                code="telegram_config_invalid",
            )
        except Exception as exc:
            return _error_response(
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
        validation_error = _validate_telegram_payload(app.state.telegram_manager, requested_payload)
        if validation_error is not None:
            return _error_response(JSONResponse, status_code=400, **validation_error)

        try:
            return await run_in_threadpool(app.state.telegram_manager.save_config, requested_payload)
        except Exception as exc:
            return _error_response(
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
            return _error_response(
                JSONResponse,
                status_code=500,
                detail="Telegram 机器人停止失败。",
                code="telegram_stop_failed",
                hint=str(exc),
            )

    return app


def start_server(settings: Settings, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Web server requires `pip install -e .[web]`.") from exc

    uvicorn.run(create_app(settings), host=host, port=port)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Start the video transcription web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", default=8000, type=int, help="bind port")
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--cookies", default=None, help="cookies.txt path")
    parser.add_argument("--model", default=None, help="whisper model name")
    parser.add_argument("--device", default=None, help="whisper device")
    args = parser.parse_args()

    settings = load_settings(
        output_dir=args.out,
        cookies_file=args.cookies,
        whisper_model=args.model,
        whisper_device=args.device,
    )
    start_server(settings, host=args.host, port=args.port)
    return 0


def _run_job_in_background(prepared_job, settings: Settings) -> None:
    try:
        run_prepared_job(prepared_job, settings)
    except Exception:
        return


def _run_transcribe_in_background(job_dir: Path, settings: Settings) -> None:
    try:
        transcribe_existing_job(job_dir, settings)
    except Exception:
        return


def _build_request_settings(base: Settings, payload: dict[str, Any]) -> Settings:
    cookies_value = str(payload.get("cookies", "")).strip()
    browser_value = str(payload.get("cookies_browser", "")).strip()
    model_value = str(payload.get("model", "")).strip()
    device_value = str(payload.get("device", "")).strip()

    return replace(
        base,
        cookies_file=Path(cookies_value).expanduser().resolve() if cookies_value else base.cookies_file,
        cookies_from_browser=browser_value or base.cookies_from_browser,
        whisper_model=model_value or base.whisper_model,
        whisper_device=device_value or base.whisper_device,
    )


def _validate_telegram_payload(manager: TelegramManager, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
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


def _error_response(
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


def _openclaw_auth_error(response_class, request, settings: Settings):
    try:
        validate_openclaw_token(settings, request.headers.get(OPENCLAW_TOKEN_HEADER))
    except PermissionError as exc:
        return _error_response(
            response_class,
            status_code=401,
            detail="OpenClaw 访问令牌无效。",
            code="openclaw_auth_invalid",
            hint="检查 X-OpenClaw-Token 或 OPENCLAW_SHARED_TOKEN 配置。",
        )
    return None
