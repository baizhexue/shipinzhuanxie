from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Thread
from typing import Any, Optional

from douyin_pipeline import __version__
from douyin_pipeline.config import Settings, load_settings
from douyin_pipeline.doctor import has_failures, run_checks
from douyin_pipeline.jobs import list_recent_manifests, read_manifest, to_public_job, write_manifest
from douyin_pipeline.pipeline import prepare_job, run_prepared_job, transcribe_existing_job


ASSET_DIR = Path(__file__).with_name("web_assets")
STATIC_DIR = ASSET_DIR / "static"
INDEX_FILE = ASSET_DIR / "index.html"


def create_app(settings: Optional[Settings] = None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("Web UI requires `pip install -e .[web]`.") from exc

    resolved_settings = settings or load_settings()
    resolved_settings.output_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Douyin Pipeline", version=__version__)
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
    async def jobs(limit: int = 8) -> dict[str, Any]:
        manifests = await run_in_threadpool(
            list_recent_manifests,
            app.state.settings.output_dir,
            limit,
        )
        return {"jobs": [to_public_job(manifest) for manifest in manifests]}

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        manifest = await run_in_threadpool(
            read_manifest,
            app.state.settings.output_dir / job_id,
        )
        if manifest is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return to_public_job(manifest)

    @app.post("/api/jobs")
    async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        raw_input = str(payload.get("raw_input", "")).strip()
        action = str(payload.get("action", "download")).strip()

        if not raw_input:
            raise HTTPException(status_code=400, detail="Please provide a share link or text.")
        if action not in {"download", "run"}:
            raise HTTPException(status_code=400, detail="Only `download` and `run` are supported.")

        request_settings = _build_request_settings(app.state.settings, payload)

        try:
            prepared_job = prepare_job(raw_input, request_settings, action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=404, detail="Job not found.")
        if manifest.get("status") in {"queued", "downloading", "transcribing", "running"}:
            raise HTTPException(status_code=409, detail="Job is still running.")
        if not manifest.get("video_path"):
            raise HTTPException(status_code=400, detail="This job has no video to transcribe.")
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

    return app


def start_server(settings: Settings, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Web server requires `pip install -e .[web]`.") from exc

    uvicorn.run(create_app(settings), host=host, port=port)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Start the Douyin Pipeline web UI.")
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
