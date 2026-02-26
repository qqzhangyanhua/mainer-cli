"""命令缓存 - 常见运维请求的快捷匹配"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from src.types import ArgValue, Instruction, RiskLevel

ArgsExtractor = Callable[[re.Match[str]], dict[str, ArgValue]]


@dataclass(frozen=True)
class CommandPattern:
    """命令匹配模式"""

    pattern: str
    worker: str
    action: str
    args_extractor: Optional[ArgsExtractor] = None
    confidence: float = 0.9
    risk_level: RiskLevel = "safe"


@dataclass(frozen=True)
class CommandMatch:
    """命令匹配结果"""

    instruction: Instruction
    confidence: float


class CommandCache:
    """基于规则的命令缓存"""

    def __init__(self, patterns: Optional[list[CommandPattern]] = None) -> None:
        self._patterns = list(patterns) if patterns else list(DEFAULT_PATTERNS)
        self._compiled: list[tuple[CommandPattern, re.Pattern[str]]] = [
            (pattern, re.compile(pattern.pattern, re.IGNORECASE)) for pattern in self._patterns
        ]
        self._hit_count: dict[str, int] = {}

    def add_pattern(self, pattern: CommandPattern) -> None:
        """新增匹配模式"""
        self._patterns.append(pattern)
        self._compiled.append((pattern, re.compile(pattern.pattern, re.IGNORECASE)))

    def match(self, text: str) -> Optional[CommandMatch]:
        """匹配用户输入"""
        normalized = text.strip()
        if not normalized:
            return None

        for pattern, compiled in self._compiled:
            match = compiled.match(normalized)
            if not match:
                continue

            args = pattern.args_extractor(match) if pattern.args_extractor else {}
            instruction = Instruction(
                worker=pattern.worker,
                action=pattern.action,
                args=args,
                risk_level=pattern.risk_level,
            )
            self._hit_count[pattern.worker] = self._hit_count.get(pattern.worker, 0) + 1
            return CommandMatch(instruction=instruction, confidence=pattern.confidence)

        return None

    def get_stats(self) -> dict[str, int]:
        """命中统计"""
        return dict(self._hit_count)


def _extract_container_list(match: re.Match[str]) -> dict[str, ArgValue]:
    return {"all": bool(match.group("all"))}


def _extract_container_logs(match: re.Match[str]) -> dict[str, ArgValue]:
    return {"container_id": match.group("name")}


def _extract_disk_usage(_: re.Match[str]) -> dict[str, ArgValue]:
    return {"path": "/"}


def _extract_large_files(match: re.Match[str]) -> dict[str, ArgValue]:
    size_raw = match.group("size")
    unit = match.group("unit")
    size = int(size_raw)
    if unit and unit.lower() == "gb":
        size *= 1024
    return {"path": ".", "min_size_mb": size}


def _extract_snapshot_cpu(_: re.Match[str]) -> dict[str, ArgValue]:
    return {"include": ["cpu"]}


def _extract_snapshot_memory(_: re.Match[str]) -> dict[str, ArgValue]:
    return {"include": ["memory"]}


def _extract_check_port(match: re.Match[str]) -> dict[str, ArgValue]:
    return {"port": int(match.group("port")), "host": "localhost"}


def _extract_list_files(_: re.Match[str]) -> dict[str, ArgValue]:
    return {"path": "."}


def _extract_git_status(_: re.Match[str]) -> dict[str, ArgValue]:
    return {"repo_dir": "."}


def _extract_check_process(match: re.Match[str]) -> dict[str, ArgValue]:
    return {"name": match.group("name")}


DEFAULT_PATTERNS: list[CommandPattern] = [
    CommandPattern(
        pattern=r"^(查看|列出|显示)(?P<all>所有)?(docker)?容器(状态)?$",
        worker="container",
        action="list_containers",
        args_extractor=_extract_container_list,
    ),
    CommandPattern(
        pattern=r"^(查看|显示)(?P<name>[\w-]+)容器(的)?日志$",
        worker="container",
        action="logs",
        args_extractor=_extract_container_logs,
    ),
    CommandPattern(
        pattern=r"^list( all)? containers$",
        worker="container",
        action="list_containers",
        args_extractor=lambda match: {"all": bool(match.group(1))},
    ),
    CommandPattern(
        pattern=r"^(查看|检查)磁盘(使用|空间)(情况)?$",
        worker="system",
        action="check_disk_usage",
        args_extractor=_extract_disk_usage,
    ),
    CommandPattern(
        pattern=r"^check disk( usage)?$",
        worker="system",
        action="check_disk_usage",
        args_extractor=_extract_disk_usage,
    ),
    CommandPattern(
        pattern=r"^(查找|搜索)(大于|超过)?(?P<size>\d+)(?P<unit>MB|GB)?(的)?文件$",
        worker="system",
        action="find_large_files",
        args_extractor=_extract_large_files,
    ),
    CommandPattern(
        pattern=r"^(查看|显示)当前目录(文件|内容)$",
        worker="system",
        action="list_files",
        args_extractor=_extract_list_files,
    ),
    CommandPattern(
        pattern=r"^(查看|显示)(系统)?(资源|状态|负载)$",
        worker="monitor",
        action="snapshot",
    ),
    CommandPattern(
        pattern=r"^(查看|显示)CPU(占用|使用率)?$",
        worker="monitor",
        action="snapshot",
        args_extractor=_extract_snapshot_cpu,
    ),
    CommandPattern(
        pattern=r"^(查看|显示)内存(占用|使用率)?$",
        worker="monitor",
        action="snapshot",
        args_extractor=_extract_snapshot_memory,
    ),
    CommandPattern(
        pattern=r"^(检查|查看)(?P<port>\d{2,5})端口(是否)?(开放|监听)?$",
        worker="monitor",
        action="check_port",
        args_extractor=_extract_check_port,
    ),
    CommandPattern(
        pattern=r"^(检查|查看)(?P<name>[\w-]+)进程$",
        worker="monitor",
        action="check_process",
        args_extractor=_extract_check_process,
    ),
    CommandPattern(
        pattern=r"^(查看|显示)git状态$",
        worker="git",
        action="status",
        args_extractor=_extract_git_status,
    ),
]
