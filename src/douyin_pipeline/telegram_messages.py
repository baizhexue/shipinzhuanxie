from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


DEFAULT_MESSAGE_LIMIT = 3900
DEFAULT_TRANSCRIPT_PREVIEW_LIMIT = 3500


def build_help_text() -> str:
    return (
        "把抖音、Bilibili、小红书、快手或 YouTube 的链接、完整分享文案发给我。\n"
        "机器人会自动下载视频并转成文字。\n"
        "命令：\n"
        "/help - 查看帮助\n"
        "/web - 查看网页地址"
    )


def build_web_missing_text() -> str:
    return "网页地址还没有配置。"


def build_job_received_text(job_id: str) -> str:
    return f"已收到任务。\n任务 ID：{job_id}\n开始下载并转写，请稍等。"


def build_failure_text(message: str, hint: Optional[str]) -> str:
    if not hint:
        return message
    return f"{message}\n建议：{hint}"


def build_failure_manifest_text(manifest: dict[str, Any]) -> str:
    message_lines = [
        "任务失败。",
        f"任务 ID：{manifest.get('job_id', '-')}",
    ]

    if manifest.get("error"):
        message_lines.append(f"原因：{manifest['error']}")

    if manifest.get("error_hint"):
        message_lines.append(f"建议：{manifest['error_hint']}")

    return "\n".join(message_lines)


def build_success_summary_text(
    public_job: dict[str, Any],
    public_base_url: Optional[str],
) -> str:
    summary_lines = [
        "任务完成。",
        f"任务 ID：{public_job.get('job_id', '-')}",
    ]

    title = public_job.get("title")
    if title:
        summary_lines.append(f"标题：{title}")

    if public_base_url:
        summary_lines.extend(build_public_links(public_job, public_base_url))

    return "\n".join(summary_lines)


def build_transcript_caption(job_id: str) -> str:
    return f"转写文本 - {job_id}"


def build_document_send_failed_text(error: Exception) -> str:
    return f"文本文件发送失败：{error}"


def build_public_links(public_job: dict[str, Any], base_url: str) -> list[str]:
    label_mapping = {
        "Video": "视频",
        "Audio": "音频",
        "Transcript": "文本",
    }
    lines = []
    for file_item in public_job.get("files", []):
        url = file_item.get("url")
        label = label_mapping.get(file_item.get("label"), "文件")
        if not url:
            continue
        lines.append(f"{label}: {base_url}{url}")
    return lines


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def phase_progress_message(manifest: dict[str, Any]) -> Optional[str]:
    phase = str(manifest.get("phase") or "")
    job_id = str(manifest.get("job_id") or "-")

    mapping = {
        "queued": f"任务已排队。\n任务 ID：{job_id}",
        "downloading": f"开始下载视频。\n任务 ID：{job_id}",
        "extracting_audio": f"视频已下载，开始提取音频。\n任务 ID：{job_id}",
        "loading_model": f"音频已准备，开始加载转写模型。\n任务 ID：{job_id}",
        "writing_transcript": f"转写完成，正在写入文本文件。\n任务 ID：{job_id}",
    }
    return mapping.get(phase)


def transcribing_progress_message(manifest: dict[str, Any], percent: float) -> str:
    job_id = str(manifest.get("job_id") or "-")
    processed = manifest.get("processed_seconds")
    duration = manifest.get("duration_seconds")
    eta = manifest.get("eta_seconds")
    parts = [f"转写进度 {int(percent)}%", f"任务 ID：{job_id}"]
    if processed is not None and duration:
        parts.append(f"已处理: {format_clock(float(processed))} / {format_clock(float(duration))}")
    if eta is not None and float(eta) > 0:
        parts.append(f"预计剩余: {format_clock(float(eta))}")
    return "\n".join(parts)


def format_clock(seconds: float) -> str:
    total_seconds = max(int(round(seconds)), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def resolve_transcript_file(output_dir: Path, transcript_path: Optional[str]) -> Optional[Path]:
    if not transcript_path:
        return None
    absolute_path = output_dir / str(transcript_path)
    if not absolute_path.exists():
        return None
    return absolute_path
