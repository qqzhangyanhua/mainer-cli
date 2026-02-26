"""Token 使用统计与预算控制"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from src.config.manager import LLMConfig


class TokenBudgetExceededError(RuntimeError):
    """Token 预算超限错误"""


@dataclass(frozen=True)
class TokenBudgetStatus:
    """Token 预算状态"""

    used: int
    limit: int
    warning: bool
    exceeded: bool


@dataclass(frozen=True)
class TokenUsageEntry:
    """Token 使用记录"""

    day: str
    tokens: int


class TokenBudgetManager:
    """Token 预算管理器"""

    def __init__(
        self,
        daily_limit: int,
        warning_threshold: float,
        usage_path: Path,
    ) -> None:
        self._daily_limit = max(0, daily_limit)
        self._warning_threshold = max(0.0, min(1.0, warning_threshold))
        self._usage_path = usage_path

    @classmethod
    def from_config(cls, config: LLMConfig) -> TokenBudgetManager:
        """从配置创建"""
        usage_path = Path(config.token_usage_path).expanduser()
        return cls(
            daily_limit=config.daily_token_limit,
            warning_threshold=config.token_warning_threshold,
            usage_path=usage_path,
        )

    def track_usage(self, total_tokens: int) -> Optional[TokenBudgetStatus]:
        """记录 token 使用量"""
        if self._daily_limit <= 0 or total_tokens <= 0:
            return None

        usage = self._load_usage()
        today = date.today().isoformat()
        used = usage.get(today, 0) + total_tokens
        usage[today] = used
        self._save_usage(usage)

        exceeded = used >= self._daily_limit
        warning = used >= int(self._daily_limit * self._warning_threshold)
        return TokenBudgetStatus(
            used=used,
            limit=self._daily_limit,
            warning=warning,
            exceeded=exceeded,
        )

    def get_today_usage(self) -> int:
        """获取今日使用量"""
        if self._daily_limit <= 0:
            return 0
        usage = self._load_usage()
        return usage.get(date.today().isoformat(), 0)

    def get_recent_usage(self, days: int = 7) -> list[TokenUsageEntry]:
        """获取近 N 天使用量"""
        usage = self._load_usage()
        today = date.today()
        entries: list[TokenUsageEntry] = []
        for offset in range(days):
            day = today - timedelta(days=offset)
            day_str = day.isoformat()
            entries.append(TokenUsageEntry(day=day_str, tokens=usage.get(day_str, 0)))
        return entries

    def reset(self, day: Optional[str] = None) -> None:
        """重置使用量"""
        if self._daily_limit <= 0:
            return
        usage = self._load_usage()
        target_day = day or date.today().isoformat()
        if target_day in usage:
            usage.pop(target_day)
            self._save_usage(usage)

    def _load_usage(self) -> dict[str, int]:
        if not self._usage_path.exists():
            return {}
        try:
            raw = self._usage_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        usage: dict[str, int] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, int):
                usage[key] = value
        return usage

    def _save_usage(self, usage: dict[str, int]) -> None:
        try:
            self._usage_path.parent.mkdir(parents=True, exist_ok=True)
            self._usage_path.write_text(
                json.dumps(usage, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return
