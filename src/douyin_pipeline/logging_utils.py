from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

_CONFIGURED_LOG_FILES: set[Path] = set()


def get_log_dir(output_dir: Path) -> Path:
    return output_dir.parent / "logs"


def configure_logging(output_dir: Path, *, service_name: str) -> Path:
    log_dir = get_log_dir(output_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{service_name}.log"

    if log_file in _CONFIGURED_LOG_FILES:
        return log_file

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = True

    _CONFIGURED_LOG_FILES.add(log_file)
    return log_file
