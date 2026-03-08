from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
import json


DEFAULT_POLL_TIMEOUT = 15
DEFAULT_RETRY_DELAY = 3.0


@dataclass(frozen=True)
class TelegramWebConfig:
    enabled: bool = False
    token: str = ""
    allowed_chat_ids: tuple[int, ...] = ()
    public_base_url: Optional[str] = None
    poll_timeout: int = DEFAULT_POLL_TIMEOUT
    retry_delay: float = DEFAULT_RETRY_DELAY
    progress_updates: bool = True


def get_runtime_dir(output_dir: Path) -> Path:
    return output_dir.parent / ".appstate"


def get_telegram_config_path(output_dir: Path) -> Path:
    return get_runtime_dir(output_dir) / "telegram_config.json"


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


def save_telegram_web_config(output_dir: Path, config: TelegramWebConfig) -> Path:
    config_path = get_telegram_config_path(output_dir)
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


def _parse_allowed_chat_ids(raw_value) -> list[int]:
    if isinstance(raw_value, list):
        return [int(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, tuple):
        return [int(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return list(parse_allowed_chat_ids_text(raw_value))
    return []
