from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


DEFAULT_MESSAGE_LIMIT = 3900
DEFAULT_TRANSCRIPT_PREVIEW_LIMIT = 3500
DEFAULT_SUMMARY_CHUNK_LIMIT = 3400


def build_help_text() -> str:
    return (
        "把抖音、Bilibili、小红书、快手或 YouTube 的链接、完整分享文案发给我。\n"
        "收到链接后，我会先让你选择处理模式，再确认是否自动总结。\n"
        "命令：\n"
        "/help - 查看帮助\n"
        "/web - 查看网页地址"
    )


def build_web_missing_text() -> str:
    return "网页地址还没有配置。"


def build_mode_selection_text() -> str:
    return (
        "已收到链接。\n"
        "请选择这条任务的处理方式：\n"
        "1. 快速转写：适合先出一版稿子\n"
        "2. 高精度转写：更慢，但准确率更高\n"
        "3. 只下载视频：先保存素材，不转文字"
    )


def build_mode_expired_text() -> str:
    return "这个选择已经失效了，请重新发送一次链接。"


def build_summary_selection_text(mode_label: str) -> str:
    return (
        f"已选择：{mode_label}\n"
        "接下来要不要自动总结？\n"
        "如果要，总结会在转写完成后自动继续跑；如果不要，就直接只给你转写稿。"
    )


def build_summary_expired_text() -> str:
    return "这个总结选项已经失效了，请重新发送一条链接。"


def build_job_started_text(
    job_id: str,
    *,
    mode_label: str,
    action: str,
    summary_label: Optional[str] = None,
) -> str:
    lines = [
        "已开始处理。",
        f"任务 ID：{job_id}",
        f"模式：{mode_label}",
    ]
    if summary_label:
        lines.append(f"总结：{summary_label}")

    if action == "download":
        lines.append("正在下载视频，请稍等。")
    else:
        lines.append("正在下载并转写，请稍等。")
    return "\n".join(lines)


def build_summary_started_text(job_id: str, style_label: str) -> str:
    return f"已开始总结。\n任务 ID：{job_id}\n风格：{style_label}"


def build_summary_completed_text(job_id: str, style_label: str, title: str) -> str:
    return f"总结已完成。\n任务 ID：{job_id}\n风格：{style_label}\n标题：{title}"


def build_summary_failed_text(style_label: str, message: str) -> str:
    return f"{style_label}总结失败。\n原因：{message}"


def build_summary_document_caption(title: str, style_label: str) -> str:
    return f"{style_label}总结 - {title}"


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
        "Summary": "总结",
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


def split_message_chunks(value: str, limit: int = DEFAULT_SUMMARY_CHUNK_LIMIT) -> list[str]:
    text = value.strip()
    if not text:
        return []

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        split_at = text.rfind("\n", 0, limit)
        if split_at < limit * 0.6:
            split_at = limit

        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()

    return chunks


def phase_progress_message(manifest: dict[str, Any]) -> Optional[str]:
    phase = str(manifest.get("phase") or "")
    job_id = str(manifest.get("job_id") or "-")
    detail = str(manifest.get("detail") or "").strip()

    mapping = {
        "queued": f"任务已排队。\n任务 ID：{job_id}",
        "downloading": f"开始下载视频。\n任务 ID：{job_id}",
        "extracting_audio": f"视频已下载，开始提取音频。\n任务 ID：{job_id}",
        "loading_model": f"音频已准备，开始加载转写模型。\n任务 ID：{job_id}",
        "writing_transcript": f"转写完成，正在写入文本文件。\n任务 ID：{job_id}",
    }
    message = mapping.get(phase)
    if not message:
        return None
    if detail and detail not in message:
        return f"{message}\n当前状态：{detail}"
    return message


def transcribing_progress_message(manifest: dict[str, Any], percent: float) -> str:
    job_id = str(manifest.get("job_id") or "-")
    processed = manifest.get("processed_seconds")
    duration = manifest.get("duration_seconds")
    eta = manifest.get("eta_seconds")
    parts = [f"转写进度 {int(percent)}%", f"任务 ID：{job_id}"]
    if processed is not None and duration:
        parts.append(f"已处理：{format_clock(float(processed))} / {format_clock(float(duration))}")
    if eta is not None and float(eta) > 0:
        parts.append(f"预计剩余：{format_clock(float(eta))}")
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
