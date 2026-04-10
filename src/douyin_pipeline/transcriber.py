from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from time import perf_counter
import re
import subprocess
from typing import Optional, Union
import wave

from douyin_pipeline.config import Settings

DEFAULT_WHISPER_BEAM_SIZE = 5
EXTRACT_AUDIO_PROGRESS_PERCENT = 10.0
MODEL_LOADING_PROGRESS_PERCENT = 18.0
TRANSCRIBING_BASE_PROGRESS_PERCENT = 20.0
TRANSCRIBING_PROGRESS_SPAN = 76.0
WRITING_TRANSCRIPT_PROGRESS_PERCENT = 98.0
COMPLETED_PROGRESS_PERCENT = 100.0
SIMPLIFIED_CHINESE_INITIAL_PROMPT = (
    "以下是简体中文视频转写稿，请优先输出简体中文，保留正常标点、常见互联网词汇和专有名词。"
)


@dataclass(frozen=True)
class TranscriptResult:
    audio_path: Path
    transcript_path: Path
    text: str
    duration_seconds: Optional[float] = None


ProgressCallback = Callable[[dict[str, Optional[Union[float, str]]]], None]


def extract_audio(
    video_path: Path,
    settings: Settings,
    progress_callback: Optional[ProgressCallback] = None,
) -> Path:
    audio_path = video_path.with_suffix(".wav")
    _emit_progress(
        progress_callback,
        phase="extracting_audio",
        progress_percent=EXTRACT_AUDIO_PROGRESS_PERCENT,
        eta_seconds=None,
        processed_seconds=0.0,
        duration_seconds=None,
        detail="Extracting audio track.",
    )
    command = [
        *settings.ffmpeg_cmd,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Audio extraction failed.\n"
            f"command: {' '.join(command)}\n"
            f"stderr: {completed.stderr.strip()}"
        )

    return audio_path


def transcribe_video(
    video_path: Path,
    settings: Settings,
    progress_callback: Optional[ProgressCallback] = None,
) -> TranscriptResult:
    audio_path = extract_audio(video_path, settings, progress_callback)
    total_duration = _audio_duration_seconds(audio_path)
    _emit_progress(
        progress_callback,
        phase="loading_model",
        progress_percent=MODEL_LOADING_PROGRESS_PERCENT,
        eta_seconds=None,
        processed_seconds=0.0,
        duration_seconds=total_duration,
        detail="Loading transcription model.",
    )
    text = _transcribe_audio(
        audio_path,
        settings,
        total_duration=total_duration,
        progress_callback=progress_callback,
    )
    transcript_path = video_path.with_suffix(".txt")
    _emit_progress(
        progress_callback,
        phase="writing_transcript",
        progress_percent=WRITING_TRANSCRIPT_PROGRESS_PERCENT,
        eta_seconds=0.0,
        processed_seconds=total_duration,
        duration_seconds=total_duration,
        detail="Writing transcript file.",
    )
    transcript_path.write_text(text, encoding="utf-8")
    _emit_progress(
        progress_callback,
        phase="completed",
        progress_percent=COMPLETED_PROGRESS_PERCENT,
        eta_seconds=0.0,
        processed_seconds=total_duration,
        duration_seconds=total_duration,
        detail="Transcript completed.",
    )
    return TranscriptResult(
        audio_path=audio_path,
        transcript_path=transcript_path,
        text=text,
        duration_seconds=total_duration,
    )


def _transcribe_audio(
    audio_path: Path,
    settings: Settings,
    *,
    total_duration: Optional[float],
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    segments, info = _run_transcription_with_fallback(audio_path, settings)
    resolved_duration = total_duration or float(getattr(info, "duration", 0.0) or 0.0)
    _emit_progress(
        progress_callback,
        phase="transcribing",
        progress_percent=TRANSCRIBING_BASE_PROGRESS_PERCENT,
        eta_seconds=None,
        processed_seconds=0.0,
        duration_seconds=resolved_duration or None,
        detail="Transcribing audio.",
    )

    lines = []
    started_at = perf_counter()
    processed_seconds = 0.0
    detected_language = str(getattr(info, "language", "") or "").lower()
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(text)

        processed_seconds = max(
            processed_seconds,
            float(getattr(segment, "end", 0.0) or 0.0),
        )
        _emit_segment_progress(
            progress_callback,
            processed_seconds=processed_seconds,
            total_duration=resolved_duration,
            started_at=started_at,
        )

    if not lines:
        return ""

    return _normalize_transcript_text(
        "\n".join(lines),
        detected_language=detected_language,
    )


def _create_whisper_model(settings: Settings):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -e .[asr]"
        ) from exc

    try:
        return WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
        )
    except Exception as exc:
        if settings.whisper_device == "auto" and _should_retry_whisper_on_cpu(exc):
            return WhisperModel(
                settings.whisper_model,
                device="cpu",
            )
        raise


def _run_transcription_with_fallback(audio_path: Path, settings: Settings):
    model = _create_whisper_model(settings)
    transcribe_options = _build_transcribe_options(settings)
    try:
        return model.transcribe(str(audio_path), **transcribe_options)
    except Exception as exc:
        if settings.whisper_device == "auto" and _should_retry_whisper_on_cpu(exc):
            cpu_settings = replace(settings, whisper_device="cpu")
            cpu_model = _create_whisper_model(cpu_settings)
            return cpu_model.transcribe(str(audio_path), **transcribe_options)
        raise


def _build_transcribe_options(settings: Settings) -> dict[str, object]:
    options: dict[str, object] = {
        "vad_filter": True,
        "beam_size": max(int(settings.whisper_beam_size or DEFAULT_WHISPER_BEAM_SIZE), 1),
    }
    language = _normalize_language_hint(settings.whisper_language)
    if language:
        options["language"] = language
        initial_prompt = _build_initial_prompt(language)
        if initial_prompt:
            options["initial_prompt"] = initial_prompt
    return options


def _normalize_language_hint(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    text = value.strip().lower()
    if not text or text == "auto":
        return None
    return text


def _build_initial_prompt(language: str) -> Optional[str]:
    if language.startswith("zh"):
        return SIMPLIFIED_CHINESE_INITIAL_PROMPT
    return None


def _should_retry_whisper_on_cpu(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "cublas",
        "cudnn",
        "cuda",
        "cublas64_12.dll",
        "libcublas",
        "libcudnn",
    )
    return any(marker in text for marker in markers)


def _normalize_transcript_text(text: str, *, detected_language: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""

    if not _should_convert_to_simplified(normalized, detected_language):
        return normalized

    converter = _load_opencc_converter()
    if converter is None:
        return normalized

    simplified = converter.convert(normalized)
    return _normalize_mainland_terms(simplified)


def _normalize_mainland_terms(text: str) -> str:
    normalized = text
    for source, target in _MAINLAND_TERM_REPLACEMENTS:
        normalized = normalized.replace(source, target)
    return normalized


def _should_convert_to_simplified(text: str, detected_language: str) -> bool:
    language = detected_language.strip().lower()
    if language.startswith("zh"):
        return True

    if _contains_japanese_kana(text) or _contains_hangul(text):
        return False

    return _contains_cjk(text)


@lru_cache(maxsize=1)
def _load_opencc_converter():
    try:
        from opencc import OpenCC
    except ImportError:
        return None

    return OpenCC("t2s")


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))


def _contains_japanese_kana(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", text))


def _contains_hangul(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7af]", text))


_MAINLAND_TERM_REPLACEMENTS = (
    ("连结", "链接"),
    ("影片", "视频"),
    ("视讯", "视频"),
    ("资讯", "信息"),
    ("软体", "软件"),
    ("程式", "程序"),
    ("帐号", "账号"),
    ("帐户", "账户"),
    ("联络", "联系"),
    ("装置", "设备"),
    ("透过", "通过"),
    ("录影", "录像"),
    ("登入", "登录"),
)


def _audio_duration_seconds(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        frame_rate = wav_file.getframerate()

    if frame_rate <= 0:
        return 0.0
    return frame_count / frame_rate


def _emit_segment_progress(
    progress_callback: Optional[ProgressCallback],
    *,
    processed_seconds: float,
    total_duration: float,
    started_at: float,
) -> None:
    if total_duration <= 0:
        _emit_progress(
            progress_callback,
            phase="transcribing",
            progress_percent=TRANSCRIBING_BASE_PROGRESS_PERCENT + (TRANSCRIBING_PROGRESS_SPAN * 0.5),
            eta_seconds=None,
            processed_seconds=processed_seconds,
            duration_seconds=None,
            detail="Transcribing audio.",
        )
        return

    clamped_processed = min(processed_seconds, total_duration)
    completion_ratio = clamped_processed / total_duration
    progress_percent = TRANSCRIBING_BASE_PROGRESS_PERCENT + (completion_ratio * TRANSCRIBING_PROGRESS_SPAN)
    elapsed = max(perf_counter() - started_at, 0.001)
    eta_seconds = _estimate_eta_seconds(
        processed_seconds=clamped_processed,
        total_duration=total_duration,
        elapsed_seconds=elapsed,
    )
    _emit_progress(
        progress_callback,
        phase="transcribing",
        progress_percent=progress_percent,
        eta_seconds=eta_seconds,
        processed_seconds=clamped_processed,
        duration_seconds=total_duration,
        detail="Transcribing audio.",
    )


def _estimate_eta_seconds(
    *,
    processed_seconds: float,
    total_duration: float,
    elapsed_seconds: float,
) -> Optional[float]:
    if processed_seconds <= 0 or total_duration <= 0 or elapsed_seconds <= 0:
        return None

    speed = processed_seconds / elapsed_seconds
    if speed <= 0:
        return None

    remaining_seconds = max(total_duration - processed_seconds, 0.0)
    return remaining_seconds / speed


def _emit_progress(
    progress_callback: Optional[ProgressCallback],
    *,
    phase: str,
    progress_percent: float,
    eta_seconds: Optional[float],
    processed_seconds: Optional[float],
    duration_seconds: Optional[float],
    detail: str,
) -> None:
    if progress_callback is None:
        return

    progress_callback(
        {
            "phase": phase,
            "progress_percent": round(max(0.0, min(progress_percent, 100.0)), 1),
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
            "processed_seconds": round(processed_seconds, 1)
            if processed_seconds is not None
            else None,
            "duration_seconds": round(duration_seconds, 1)
            if duration_seconds is not None
            else None,
            "detail": detail,
        }
    )
