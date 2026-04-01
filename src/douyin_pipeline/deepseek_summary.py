from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Optional
import re
import urllib.error
import urllib.request

from douyin_pipeline.config import Settings
from douyin_pipeline.runtime_config import (
    DEFAULT_SUMMARY_PROMPTS,
    load_summary_prompt_config,
)


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 120
DIRECT_SUMMARY_CHAR_LIMIT = 18_000
CHUNK_SUMMARY_CHAR_LIMIT = 12_000
SUMMARY_MAX_TOKENS = 2_000
PARTIAL_SUMMARY_MAX_TOKENS = 1_100

SUMMARY_STYLE_LABELS = {
    "general": "通用",
    "plain": "大白话",
    "knowledge": "知识型",
}

SYSTEM_PROMPT = (
    "你是一个严谨的中文内容总结助手。"
    "只根据用户提供的原文总结，不要编造，不要补充原文没有的信息。"
)

TITLE_AND_BODY_SCHEMA = (
    "你必须只输出一个合法 JSON 对象，不要输出任何 JSON 以外的内容。\n"
    "JSON 字段要求：\n"
    "1. title: 中文标题，准确具体，能让人一眼看出内容主题，尽量不超过 18 个字；\n"
    "2. summary_markdown: Markdown 正文，不要再写一级标题。"
)


class SummaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SummaryResult:
    style: str
    label: str
    title: str
    text: str
    markdown: str
    summary_path: Path


def summarize_to_file(
    transcript_text: str,
    *,
    style: str,
    job_dir: Path,
    settings: Settings,
) -> SummaryResult:
    title, summary_text = summarize_text(transcript_text, style=style, settings=settings)
    markdown = _build_markdown_document(title, summary_text)
    summary_path = job_dir / _build_summary_filename(style, title)
    summary_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return SummaryResult(
        style=style,
        label=get_summary_style_label(style),
        title=title,
        text=summary_text,
        markdown=markdown,
        summary_path=summary_path,
    )


def summarize_text(transcript_text: str, *, style: str, settings: Settings) -> tuple[str, str]:
    if not settings.deepseek_api_key:
        raise SummaryError("DeepSeek API key is not configured.")

    cleaned_text = transcript_text.strip()
    if not cleaned_text:
        raise SummaryError("Transcript text is empty.")

    base_prompt = _resolve_style_prompt(style, settings)
    if len(cleaned_text) <= DIRECT_SUMMARY_CHAR_LIMIT:
        return _request_titled_summary(
            settings,
            prompt=_build_direct_prompt(base_prompt, cleaned_text),
            max_tokens=SUMMARY_MAX_TOKENS,
        )

    chunks = _split_text(cleaned_text, CHUNK_SUMMARY_CHAR_LIMIT)
    partial_summaries: list[str] = []
    total_chunks = len(chunks)
    logger.info("summary chunked style=%s chunks=%s", style, total_chunks)

    for index, chunk in enumerate(chunks, start=1):
        partial_prompt = (
            f"{base_prompt}\n\n"
            f"下面是原文的第 {index}/{total_chunks} 段，请只总结这一段，保持忠于原文。\n\n"
            f"原文片段：\n{chunk}"
        )
        partial_summaries.append(
            _request_text_summary(
                settings,
                prompt=partial_prompt,
                max_tokens=PARTIAL_SUMMARY_MAX_TOKENS,
            )
        )

    merged_prompt = (
        f"{base_prompt}\n\n"
        "下面是同一份长内容分段总结后的结果，请整合成一份完整总结，去重、合并重复信息、保留关键信息。\n\n"
        f"{_format_partial_summaries(partial_summaries)}"
    )
    return _request_titled_summary(settings, prompt=merged_prompt, max_tokens=SUMMARY_MAX_TOKENS)


def get_summary_style_label(style: str) -> str:
    try:
        return SUMMARY_STYLE_LABELS[style]
    except KeyError as exc:
        raise SummaryError(f"Unsupported summary style: {style}") from exc


def _resolve_style_prompt(style: str, settings: Settings) -> str:
    prompt_config = load_summary_prompt_config(settings.output_dir)
    prompt_mapping = {
        "general": prompt_config.general,
        "plain": prompt_config.plain,
        "knowledge": prompt_config.knowledge,
    }
    prompt = prompt_mapping.get(style)
    if prompt:
        return prompt
    if style in DEFAULT_SUMMARY_PROMPTS:
        return DEFAULT_SUMMARY_PROMPTS[style]
    raise SummaryError(f"Unsupported summary style: {style}")


def _build_direct_prompt(base_prompt: str, transcript_text: str) -> str:
    return f"{base_prompt}\n\n{TITLE_AND_BODY_SCHEMA}\n\n原文如下：\n{transcript_text}"


def _format_partial_summaries(partials: list[str]) -> str:
    return "\n\n".join(
        f"第 {index} 段摘要：\n{summary.strip()}"
        for index, summary in enumerate(partials, start=1)
        if summary.strip()
    )


def _build_markdown_document(title: str, summary_text: str) -> str:
    return f"# {title}\n\n{summary_text.strip()}"


def _build_summary_filename(style: str, title: str) -> str:
    style_label = get_summary_style_label(style)
    safe_title = _sanitize_filename(title) or "未命名内容"
    return f"{safe_title}-{style_label}总结.md"


def _sanitize_filename(value: str) -> str:
    sanitized = value.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    sanitized = re.sub(r'[<>:"/\\|?*]+', " ", sanitized).strip().strip(".")
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized[:80].strip()


def _split_text(text: str, chunk_size: int) -> list[str]:
    segments: list[str] = []
    normalized = text.strip()
    while normalized:
        if len(normalized) <= chunk_size:
            segments.append(normalized)
            break

        split_at = normalized.rfind("\n", 0, chunk_size)
        if split_at < chunk_size * 0.6:
            split_at = normalized.rfind("。", 0, chunk_size)
        if split_at < chunk_size * 0.5:
            split_at = chunk_size

        segments.append(normalized[:split_at].strip())
        normalized = normalized[split_at:].lstrip()

    return [segment for segment in segments if segment]


def _request_text_summary(settings: Settings, *, prompt: str, max_tokens: int) -> str:
    payload = {
        "model": settings.deepseek_model or DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "stream": False,
        "max_tokens": max_tokens,
    }
    content = _request_completion(settings, payload=payload)
    if not content:
        raise SummaryError("DeepSeek API returned an empty summary.")
    return content.strip()


def _request_titled_summary(settings: Settings, *, prompt: str, max_tokens: int) -> tuple[str, str]:
    payload = {
        "model": settings.deepseek_model or DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    content = _request_completion(settings, payload=payload)
    if not content:
        raise SummaryError("DeepSeek API returned an empty summary.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SummaryError(f"DeepSeek summary JSON parse failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise SummaryError("DeepSeek summary JSON payload is not an object.")

    title = str(parsed.get("title") or "").strip()
    summary_markdown = str(parsed.get("summary_markdown") or "").strip()
    if not title:
        raise SummaryError("DeepSeek summary title is empty.")
    if not summary_markdown:
        raise SummaryError("DeepSeek summary body is empty.")
    return title, summary_markdown


def _request_completion(settings: Settings, *, payload: dict) -> str:
    request = urllib.request.Request(
        f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.deepseek_api_key}",
        },
        method="POST",
    )

    timeout_seconds = max(int(settings.deepseek_timeout_seconds or DEFAULT_TIMEOUT_SECONDS), 30)

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SummaryError(f"DeepSeek API HTTP error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SummaryError(f"DeepSeek API request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SummaryError(f"DeepSeek API returned invalid JSON: {exc}") from exc

    content = _extract_response_text(response_payload)
    if not content:
        raise SummaryError("DeepSeek API returned an empty completion.")
    return content.strip()


def _extract_response_text(payload: dict) -> Optional[str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None

    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    if isinstance(content, str):
        return content
    return None
