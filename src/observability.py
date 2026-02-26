"""结构化日志输出"""

from __future__ import annotations

import json
import logging
from datetime import datetime

LOGGER_NAME = "opsai"


def configure_structured_logging(level: int = logging.INFO) -> None:
    """配置结构化日志输出"""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)


def log_event(event: str, **fields: object) -> None:
    """输出结构化日志事件"""
    logger = logging.getLogger(LOGGER_NAME)
    payload: dict[str, object] = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    payload.update(fields)
    logger.info(json.dumps(payload, ensure_ascii=False))
