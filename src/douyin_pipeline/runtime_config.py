from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
import json


DEFAULT_POLL_TIMEOUT = 15
DEFAULT_RETRY_DELAY = 3.0

DEFAULT_SUMMARY_PROMPTS = {
    "general": (
        "请阅读以下内容，并用中文帮我做一份高质量总结。\n\n"
        "要求：\n"
        "1. 提炼核心观点，不要遗漏关键信息；\n"
        "2. 用清晰的结构输出，分点表述；\n"
        "3. 先给“整体概述”，再给“重点信息”；\n"
        "4. 如果内容里有结论、建议、风险、数据，请单独列出；\n"
        "5. 不要胡乱补充原文没有的信息。"
    ),
    "plain": (
        "你现在是一个很会提炼重点的内容助手。\n\n"
        "请把下面内容总结成“人话”，让我一眼看懂。\n\n"
        "输出要求：\n"
        "- 先告诉我“这段内容主要在讲什么”；\n"
        "- 再告诉我“最重要的几点”；\n"
        "- 如果有结论，直接告诉我结论；\n"
        "- 如果有建议，直接告诉我该怎么做；\n"
        "- 尽量不要用太书面、太绕的话。"
    ),
    "knowledge": (
        "请把下面内容总结成适合学习和复盘的笔记。\n\n"
        "要求：\n"
        "1. 提炼主题；\n"
        "2. 拆分知识点；\n"
        "3. 标注重点、难点、易忽略点；\n"
        "4. 最后补一个“看完后应该记住什么”；\n"
        "5. 输出尽量像一份高质量学习笔记。"
    ),
}


@dataclass(frozen=True)
class TelegramWebConfig:
    enabled: bool = False
    token: str = ""
    allowed_chat_ids: tuple[int, ...] = ()
    public_base_url: Optional[str] = None
    poll_timeout: int = DEFAULT_POLL_TIMEOUT
    retry_delay: float = DEFAULT_RETRY_DELAY
    progress_updates: bool = True


@dataclass(frozen=True)
class SummaryPromptConfig:
    general: str = DEFAULT_SUMMARY_PROMPTS["general"]
    plain: str = DEFAULT_SUMMARY_PROMPTS["plain"]
    knowledge: str = DEFAULT_SUMMARY_PROMPTS["knowledge"]


def get_runtime_dir(output_dir: Path) -> Path:
    return output_dir.parent / ".appstate"


def get_telegram_config_path(output_dir: Path) -> Path:
    return get_runtime_dir(output_dir) / "telegram_config.json"


def get_summary_prompt_config_path(output_dir: Path) -> Path:
    return get_runtime_dir(output_dir) / "summary_prompts.json"


def load_telegram_web_config(output_dir: Path) -> TelegramWebConfig:
    config_path = get_telegram_config_path(output_dir)
    if not config_path.exists():
        return TelegramWebConfig()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return TelegramWebConfig()

    if not isinstance(payload, dict):
        return TelegramWebConfig()

    return TelegramWebConfig(
        enabled=bool(payload.get("enabled", False)),
        token=str(payload.get("token") or "").strip(),
        allowed_chat_ids=tuple(_parse_allowed_chat_ids(payload.get("allowed_chat_ids", []))),
        public_base_url=_normalize_base_url(payload.get("public_base_url")),
        poll_timeout=max(int(payload.get("poll_timeout") or DEFAULT_POLL_TIMEOUT), 1),
        retry_delay=max(float(payload.get("retry_delay") or DEFAULT_RETRY_DELAY), 1.0),
        progress_updates=bool(payload.get("progress_updates", True)),
    )


def load_summary_prompt_config(output_dir: Path) -> SummaryPromptConfig:
    config_path = get_summary_prompt_config_path(output_dir)
    if not config_path.exists():
        return SummaryPromptConfig()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return SummaryPromptConfig()

    if not isinstance(payload, dict):
        return SummaryPromptConfig()

    return SummaryPromptConfig(
        general=_normalize_summary_prompt(payload.get("general"), DEFAULT_SUMMARY_PROMPTS["general"]),
        plain=_normalize_summary_prompt(payload.get("plain"), DEFAULT_SUMMARY_PROMPTS["plain"]),
        knowledge=_normalize_summary_prompt(payload.get("knowledge"), DEFAULT_SUMMARY_PROMPTS["knowledge"]),
    )


def save_telegram_web_config(output_dir: Path, config: TelegramWebConfig) -> Path:
    config_path = get_telegram_config_path(output_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config_path


def save_summary_prompt_config(output_dir: Path, config: SummaryPromptConfig) -> Path:
    config_path = get_summary_prompt_config_path(output_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config_path


def update_telegram_web_config(
    output_dir: Path,
    payload: dict,
) -> TelegramWebConfig:
    current = load_telegram_web_config(output_dir)
    clear_token = bool(payload.get("clear_token", False))
    token_value = str(payload.get("token", "") or "").strip()
    public_base_url = str(payload.get("public_base_url", "") or "").strip()
    allowed_chat_ids_text = str(payload.get("allowed_chat_ids", "") or "").strip()
    progress_updates = payload.get("progress_updates")

    updated = TelegramWebConfig(
        enabled=bool(payload.get("enabled", current.enabled)),
        token="" if clear_token else (token_value or current.token),
        allowed_chat_ids=(
            parse_allowed_chat_ids_text(allowed_chat_ids_text)
            if "allowed_chat_ids" in payload
            else current.allowed_chat_ids
        ),
        public_base_url=_normalize_base_url(public_base_url) if "public_base_url" in payload else current.public_base_url,
        poll_timeout=max(int(payload.get("poll_timeout", current.poll_timeout)), 1),
        retry_delay=max(float(payload.get("retry_delay", current.retry_delay)), 1.0),
        progress_updates=bool(progress_updates) if progress_updates is not None else current.progress_updates,
    )
    save_telegram_web_config(output_dir, updated)
    return updated


def update_summary_prompt_config(output_dir: Path, payload: dict) -> SummaryPromptConfig:
    current = load_summary_prompt_config(output_dir)
    updated = SummaryPromptConfig(
        general=_normalize_summary_prompt(payload.get("general"), current.general),
        plain=_normalize_summary_prompt(payload.get("plain"), current.plain),
        knowledge=_normalize_summary_prompt(payload.get("knowledge"), current.knowledge),
    )
    save_summary_prompt_config(output_dir, updated)
    return updated


def telegram_web_config_to_public_payload(config: TelegramWebConfig) -> dict:
    return {
        "enabled": config.enabled,
        "has_token": bool(config.token),
        "token_masked": mask_token(config.token),
        "allowed_chat_ids": list(config.allowed_chat_ids),
        "allowed_chat_ids_text": ",".join(str(value) for value in config.allowed_chat_ids),
        "public_base_url": config.public_base_url or "",
        "poll_timeout": config.poll_timeout,
        "retry_delay": config.retry_delay,
        "progress_updates": config.progress_updates,
    }


def summary_prompt_config_to_public_payload(config: SummaryPromptConfig) -> dict:
    return {
        "general": config.general,
        "plain": config.plain,
        "knowledge": config.knowledge,
        "defaults": dict(DEFAULT_SUMMARY_PROMPTS),
    }


def parse_allowed_chat_ids_text(raw_value: str) -> tuple[int, ...]:
    values = []
    for item in raw_value.split(","):
        text = item.strip()
        if not text:
            continue
        values.append(int(text))
    return tuple(values)


def mask_token(token: str) -> str:
    value = token.strip()
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _normalize_base_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return text.rstrip("/")


def _normalize_summary_prompt(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _parse_allowed_chat_ids(raw_value) -> list[int]:
    if isinstance(raw_value, list):
        return [int(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, tuple):
        return [int(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return list(parse_allowed_chat_ids_text(raw_value))
    return []
