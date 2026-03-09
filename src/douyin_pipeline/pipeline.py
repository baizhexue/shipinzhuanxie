from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.downloader import DownloadResult, create_job_dir, download_video
from douyin_pipeline.errors import UserFacingError, classify_exception
from douyin_pipeline.jobs import read_manifest, relative_to, write_manifest
from douyin_pipeline.parser import detect_source_platform, extract_share_url
from douyin_pipeline.transcriber import TranscriptResult, transcribe_video


JobAction = Literal["download", "run"]
StatusCallback = Optional[Callable[[dict[str, Any]], None]]


@dataclass(frozen=True)
class PreparedJob:
    raw_input: str
    source_url: str
    action: JobAction
    created_at: str
    job_dir: Path


def process_job(
    raw_input: str,
    settings: Settings,
    action: JobAction,
    *,
    status_callback: StatusCallback = None,
) -> dict[str, Any]:
    prepared_job = prepare_job(raw_input, settings, action)
    return run_prepared_job(prepared_job, settings, status_callback=status_callback)


def transcribe_existing_job(
    job_dir: Path,
    settings: Settings,
    *,
    status_callback: StatusCallback = None,
) -> dict[str, Any]:
    manifest = read_manifest(job_dir)
    if manifest is None:
        raise ValueError("Job manifest not found.")

    video_rel = manifest.get("video_path")
    if not video_rel:
        raise ValueError("This job does not have a downloadable video to transcribe.")

    transcript_rel = manifest.get("transcript_path")
    if transcript_rel:
        return manifest

    video_path = settings.output_dir / str(video_rel)
    if not video_path.exists():
        raise ValueError("The downloaded video file is missing.")

    _write_existing_status(
        job_dir=job_dir,
        manifest=manifest,
        settings=settings,
        status="transcribing",
        detail="准备为已下载视频生成文字。",
        error=None,
        error_info=None,
        phase="extracting_audio",
        progress_percent=34.0,
        eta_seconds=None,
        processed_seconds=0.0,
        duration_seconds=None,
        status_callback=status_callback,
    )

    try:
        transcript_result = transcribe_video(
            video_path,
            settings,
            progress_callback=lambda payload: _write_existing_status(
                job_dir=job_dir,
                manifest=read_manifest(job_dir) or manifest,
                settings=settings,
                status="transcribing",
                detail=str(payload["detail"]),
                error=None,
                error_info=None,
                phase=_as_text(payload.get("phase")),
                progress_percent=_as_float(payload.get("progress_percent")),
                eta_seconds=_as_float(payload.get("eta_seconds")),
                processed_seconds=_as_float(payload.get("processed_seconds")),
                duration_seconds=_as_float(payload.get("duration_seconds")),
                status_callback=status_callback,
            ),
        )
        updated_manifest = _merge_existing_manifest(
            manifest,
            settings=settings,
            status="success",
            detail="转写完成。",
            transcript_result=transcript_result,
            error=None,
            error_info=None,
            phase="completed",
            progress_percent=100.0,
            eta_seconds=0.0,
            processed_seconds=_infer_processed_seconds(transcript_result),
            duration_seconds=_infer_processed_seconds(transcript_result),
        )
        _write_manifest_with_callback(job_dir, updated_manifest, status_callback)
        return updated_manifest
    except Exception as exc:
        error_info = classify_exception(exc)
        updated_manifest = _merge_existing_manifest(
            manifest,
            settings=settings,
            status="error",
            detail="转写失败。",
            transcript_result=None,
            error=None,
            error_info=error_info,
            phase="failed",
            progress_percent=None,
            eta_seconds=None,
            processed_seconds=None,
            duration_seconds=None,
        )
        _write_manifest_with_callback(job_dir, updated_manifest, status_callback)
        raise


def prepare_job(raw_input: str, settings: Settings, action: JobAction) -> PreparedJob:
    if action not in {"download", "run"}:
        raise ValueError(f"Unsupported action: {action}")

    source_url = extract_share_url(raw_input)
    prepared_job = PreparedJob(
        raw_input=raw_input,
        source_url=source_url,
        action=action,
        created_at=datetime.now().isoformat(timespec="seconds"),
        job_dir=create_job_dir(settings.output_dir),
    )

    write_manifest(
        prepared_job.job_dir,
        _build_manifest(
            settings=settings,
            prepared_job=prepared_job,
            status="queued",
            detail="任务已创建，等待处理。",
            download_result=None,
            transcript_result=None,
            error=None,
            error_info=None,
            phase="queued",
            progress_percent=0.0,
            eta_seconds=None,
            processed_seconds=0.0,
            duration_seconds=None,
        ),
    )
    return prepared_job


def run_prepared_job(
    prepared_job: PreparedJob,
    settings: Settings,
    *,
    status_callback: StatusCallback = None,
) -> dict[str, Any]:
    download_result: Optional[DownloadResult] = None
    transcript_result: Optional[TranscriptResult] = None

    _write_status(
        settings=settings,
        prepared_job=prepared_job,
        status="downloading",
        detail="正在下载视频。",
        download_result=None,
        transcript_result=None,
        error=None,
        error_info=None,
        phase="downloading",
        progress_percent=8.0,
        eta_seconds=None,
        processed_seconds=None,
        duration_seconds=None,
        status_callback=status_callback,
    )

    try:
        download_result = download_video(
            prepared_job.source_url,
            settings,
            job_dir=prepared_job.job_dir,
        )

        if prepared_job.action == "run":
            _write_status(
                settings=settings,
                prepared_job=prepared_job,
                status="transcribing",
                detail="视频下载完成，开始准备转写。",
                download_result=download_result,
                transcript_result=None,
                error=None,
                error_info=None,
                phase="extracting_audio",
                progress_percent=34.0,
                eta_seconds=None,
                processed_seconds=0.0,
                duration_seconds=None,
                status_callback=status_callback,
            )
            transcript_result = transcribe_video(
                download_result.video_path,
                settings,
                progress_callback=lambda payload: _write_status(
                    settings=settings,
                    prepared_job=prepared_job,
                    status="transcribing",
                    detail=str(payload["detail"]),
                    download_result=download_result,
                    transcript_result=None,
                    error=None,
                    error_info=None,
                    phase=_as_text(payload.get("phase")),
                    progress_percent=_as_float(payload.get("progress_percent")),
                    eta_seconds=_as_float(payload.get("eta_seconds")),
                    processed_seconds=_as_float(payload.get("processed_seconds")),
                    duration_seconds=_as_float(payload.get("duration_seconds")),
                    status_callback=status_callback,
                ),
            )

        manifest = _build_manifest(
            settings=settings,
            prepared_job=prepared_job,
            status="success",
            detail="任务完成。",
            download_result=download_result,
            transcript_result=transcript_result,
            error=None,
            error_info=None,
            phase="completed",
            progress_percent=100.0,
            eta_seconds=0.0,
            processed_seconds=_infer_processed_seconds(transcript_result),
            duration_seconds=_infer_processed_seconds(transcript_result),
        )
        _write_manifest_with_callback(prepared_job.job_dir, manifest, status_callback)
        return manifest
    except Exception as exc:
        error_info = classify_exception(exc)
        manifest = _build_manifest(
            settings=settings,
            prepared_job=prepared_job,
            status="error",
            detail="下载或转写失败。",
            download_result=download_result,
            transcript_result=transcript_result,
            error=None,
            error_info=error_info,
            phase="failed",
            progress_percent=None,
            eta_seconds=None,
            processed_seconds=None,
            duration_seconds=None,
        )
        _write_manifest_with_callback(prepared_job.job_dir, manifest, status_callback)
        raise


def _write_status(
    *,
    settings: Settings,
    prepared_job: PreparedJob,
    status: str,
    detail: str,
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
    status_callback: StatusCallback,
) -> None:
    payload = _build_manifest(
        settings=settings,
        prepared_job=prepared_job,
        status=status,
        detail=detail,
        download_result=download_result,
        transcript_result=transcript_result,
        error=error,
        error_info=error_info,
        phase=phase,
        progress_percent=progress_percent,
        eta_seconds=eta_seconds,
        processed_seconds=processed_seconds,
        duration_seconds=duration_seconds,
    )
    _write_manifest_with_callback(prepared_job.job_dir, payload, status_callback)


def _build_manifest(
    *,
    settings: Settings,
    prepared_job: PreparedJob,
    status: str,
    detail: str,
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
) -> dict[str, Any]:
    video_path = download_result.video_path if download_result else None
    audio_path = _resolve_audio_path(download_result, transcript_result)
    transcript_path = _resolve_transcript_path(download_result, transcript_result)
    transcript_text = (
        transcript_result.text
        if transcript_result
        else _load_transcript_preview(prepared_job.job_dir)
    )

    return {
        "job_id": prepared_job.job_dir.name,
        "job_dir": prepared_job.job_dir.name,
        "created_at": prepared_job.created_at,
        "action": prepared_job.action,
        "status": status,
        "detail": detail,
        "raw_input": prepared_job.raw_input,
        "source_url": prepared_job.source_url,
        "source_platform": detect_source_platform(prepared_job.source_url),
        "title": download_result.title if download_result else None,
        "video_path": relative_to(settings.output_dir, video_path),
        "audio_path": relative_to(settings.output_dir, audio_path),
        "transcript_path": relative_to(settings.output_dir, transcript_path),
        "transcript_preview": _truncate_text(transcript_text),
        **_build_error_fields(error=error, error_info=error_info),
        "phase": phase,
        "progress_percent": progress_percent,
        "eta_seconds": eta_seconds,
        "processed_seconds": processed_seconds,
        "duration_seconds": duration_seconds,
    }


def _write_existing_status(
    *,
    job_dir: Path,
    manifest: dict[str, Any],
    settings: Settings,
    status: str,
    detail: str,
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
    status_callback: StatusCallback,
) -> None:
    payload = _merge_existing_manifest(
        manifest,
        settings=settings,
        status=status,
        detail=detail,
        transcript_result=None,
        error=error,
        error_info=error_info,
        phase=phase,
        progress_percent=progress_percent,
        eta_seconds=eta_seconds,
        processed_seconds=processed_seconds,
        duration_seconds=duration_seconds,
    )
    _write_manifest_with_callback(job_dir, payload, status_callback)


def _merge_existing_manifest(
    manifest: dict[str, Any],
    *,
    settings: Settings,
    status: str,
    detail: str,
    transcript_result: Optional[TranscriptResult],
    error: Optional[str],
    error_info: Optional[UserFacingError],
    phase: Optional[str],
    progress_percent: Optional[float],
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
) -> dict[str, Any]:
    updated = dict(manifest)
    updated["status"] = status
    updated["detail"] = detail
    updated.update(_build_error_fields(error=error, error_info=error_info))
    updated["phase"] = phase
    updated["progress_percent"] = progress_percent
    updated["eta_seconds"] = eta_seconds
    updated["processed_seconds"] = processed_seconds
    updated["duration_seconds"] = duration_seconds

    if transcript_result:
        updated["audio_path"] = relative_to(settings.output_dir, transcript_result.audio_path)
        updated["transcript_path"] = relative_to(settings.output_dir, transcript_result.transcript_path)
        updated["transcript_preview"] = _truncate_text(transcript_result.text)
    else:
        audio_rel = updated.get("audio_path")
        transcript_rel = updated.get("transcript_path")
        if not transcript_rel:
            updated["transcript_preview"] = ""

        if audio_rel:
            audio_path = settings.output_dir / str(audio_rel)
            if not audio_path.exists():
                updated["audio_path"] = None

        if transcript_rel:
            transcript_path = settings.output_dir / str(transcript_rel)
            if transcript_path.exists():
                updated["transcript_preview"] = _truncate_text(
                    transcript_path.read_text(encoding="utf-8")
                )
            else:
                updated["transcript_path"] = None
                updated["transcript_preview"] = ""

    return updated


def _resolve_audio_path(
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
) -> Optional[Path]:
    if transcript_result:
        return transcript_result.audio_path

    if not download_result:
        return None

    candidate = download_result.video_path.with_suffix(".wav")
    return candidate if candidate.exists() else None


def _build_error_fields(
    *,
    error: Optional[str],
    error_info: Optional[UserFacingError],
) -> dict[str, Optional[str]]:
    if error_info is None:
        return {
            "error": error,
            "error_code": None,
            "error_kind": None,
            "error_hint": None,
            "technical_error": None,
        }

    return {
        "error": error_info.message,
        "error_code": error_info.code,
        "error_kind": error_info.kind,
        "error_hint": error_info.hint,
        "technical_error": error_info.technical_detail,
    }


def _resolve_transcript_path(
    download_result: Optional[DownloadResult],
    transcript_result: Optional[TranscriptResult],
) -> Optional[Path]:
    if transcript_result:
        return transcript_result.transcript_path

    if not download_result:
        return None

    candidate = download_result.video_path.with_suffix(".txt")
    return candidate if candidate.exists() else None


def _load_transcript_preview(job_dir: Path) -> str:
    transcript_files = sorted(job_dir.glob("*.txt"))
    if not transcript_files:
        return ""
    return transcript_files[0].read_text(encoding="utf-8")


def _truncate_text(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _infer_processed_seconds(transcript_result: Optional[TranscriptResult]) -> Optional[float]:
    if transcript_result is None:
        return None
    return transcript_result.duration_seconds


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _as_text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _write_manifest_with_callback(
    job_dir: Path,
    payload: dict[str, Any],
    status_callback: StatusCallback,
) -> None:
    write_manifest(job_dir, payload)
    if status_callback is not None:
        status_callback(dict(payload))
