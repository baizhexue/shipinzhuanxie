from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter
import re
import subprocess
from typing import Optional, Union
import wave

from douyin_pipeline.config import Settings


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
        progress_percent=34.0,
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
        progress_percent=40.0,
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
        progress_percent=99.0,
        eta_seconds=0.0,
        processed_seconds=total_duration,
        duration_seconds=total_duration,
        detail="Writing transcript file.",
    )
    transcript_path.write_text(text, encoding="utf-8")
    _emit_progress(
        progress_callback,
        phase="completed",
        progress_percent=100.0,
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
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -e .[asr]"
        ) from exc

    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
    )
    segments, info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        beam_size=1,
    )
    resolved_duration = total_duration or float(getattr(info, "duration", 0.0) or 0.0)
    _emit_progress(
        progress_callback,
        phase="transcribing",
        progress_percent=42.0,
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


def _normalize_transcript_text(text: str, *, detected_language: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""

    if not _should_convert_to_simplified(normalized, detected_language):
        return normalized

    converter = _load_opencc_converter()
    if converter is None:
        return normalized

    return converter.convert(normalized)


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
            progress_percent=65.0,
            eta_seconds=None,
            processed_seconds=processed_seconds,
            duration_seconds=None,
            detail="Transcribing audio.",
        )
        return

    clamped_processed = min(processed_seconds, total_duration)
    completion_ratio = clamped_processed / total_duration
    progress_percent = 42.0 + (completion_ratio * 56.0)
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
