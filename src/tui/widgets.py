"""TUI 自定义组件 - 命令建议器与辅助函数"""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path
from typing import Callable

from rich.console import Console
from textual.suggester import Suggester
from textual.widgets import RichLog


class SlashCommandSuggester(Suggester):
    """斜杠命令的幽灵文本提示"""

    def __init__(self, suggestion_provider: Callable[[str], str | None]) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._suggestion_provider = suggestion_provider

    async def get_suggestion(self, value: str) -> str | None:
        return self._suggestion_provider(value)


_RICH_MARKUP_RE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")


def strip_rich_markup(text: str) -> str:
    """剥离 Rich 标记，返回纯文本"""
    return _RICH_MARKUP_RE.sub("", text)


class HistoryWriter:
    """RichLog 代理：同时维护纯文本缓冲区，供复制模式使用"""

    def __init__(self, rich_log: RichLog, plain_buffer: list[str]) -> None:
        self._rich_log = rich_log
        self._plain_buffer = plain_buffer

    def write(self, content: object) -> None:
        self._rich_log.write(content)
        if isinstance(content, str):
            self._plain_buffer.append(strip_rich_markup(content))
        else:
            buf = StringIO()
            console = Console(file=buf, no_color=True, width=120)
            console.print(content)
            self._plain_buffer.append(buf.getvalue().rstrip())

    def clear(self) -> None:
        self._rich_log.clear()
        self._plain_buffer.clear()


def format_path(path: Path) -> str:
    """格式化路径为短路径（优先 ~）"""
    try:
        home = Path.home()
        if path == home:
            return "~"
        if home in path.parents:
            return f"~/{path.relative_to(home)}"
    except Exception:
        return str(path)
    return str(path)


def mask_secret(value: str) -> str:
    """敏感信息脱敏显示"""
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def truncate_text(text: str, max_length: int) -> str:
    """截断文本用于摘要显示"""
    text = text.strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}..."


def is_subsequence(needle: str, haystack: str) -> bool:
    """判断 needle 是否为 haystack 的子序列"""
    index = 0
    for ch in needle:
        index = haystack.find(ch, index)
        if index == -1:
            return False
        index += 1
    return True


def subsequence_gap(needle: str, haystack: str) -> int:
    """子序列匹配的间隔评分（越小越好）"""
    index = -1
    gaps = 0
    for ch in needle:
        next_index = haystack.find(ch, index + 1)
        if next_index == -1:
            return 10_000
        gaps += next_index - index - 1
        index = next_index
    return gaps
