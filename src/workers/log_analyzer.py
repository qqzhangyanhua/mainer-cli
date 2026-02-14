"""日志分析 Worker - 纯本地计算，不依赖 LLM"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional, Union

from src.types import (
    ArgValue,
    LogAnalysis,
    LogEntry,
    LogLevel,
    LogPatternCount,
    LogTrendPoint,
    WorkerResult,
)
from src.workers.base import BaseWorker

# 日志级别识别正则（按优先级排序）
_LEVEL_PATTERNS: list[tuple[str, LogLevel]] = [
    (r"\bFATAL\b", "FATAL"),
    (r"\bERROR\b", "ERROR"),
    (r"\bERR\b", "ERROR"),
    (r"\bWARN(?:ING)?\b", "WARN"),
    (r"\bINFO\b", "INFO"),
    (r"\bDEBUG\b", "DEBUG"),
    (r"\bTRACE\b", "TRACE"),
]

# 时间戳正则（常见格式）
_TIMESTAMP_PATTERNS: list[str] = [
    # ISO 8601: 2024-01-15T09:30:45.123Z
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    # Common: 2024-01-15 09:30:45
    r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?",
    # Syslog: Jan 15 09:30:45
    r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",
    # Docker JSON: 2024-01-15T09:30:45.123456789Z
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z",
    # Nginx: 15/Jan/2024:09:30:45 +0800
    r"\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}",
    # Time only: 09:30:45
    r"\d{2}:\d{2}:\d{2}",
]

# 用于模式归一化的替换规则（顺序重要：UUID 在 HEX 之前）
_NORMALIZE_RULES: list[tuple[str, str]] = [
    # UUID（必须在 HEX 之前）
    (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<UUID>"),
    # IP 地址（必须在纯数字之前）
    (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>"),
    # 十六进制 ID（容器 ID、commit hash 等）
    (r"\b[0-9a-f]{8,}\b", "<HEX>"),
    # 纯数字（PID、端口、行号等）
    (r"\b\d+\b", "<N>"),
    # 连续空格压缩
    (r"\s+", " "),
]

# 错误级别集合
_ERROR_LEVELS: set[LogLevel] = {"ERROR", "FATAL"}
_WARN_LEVELS: set[LogLevel] = {"WARN"}


class LogAnalyzerWorker(BaseWorker):
    """日志分析 Worker

    纯本地计算，不调用 LLM。负责：
    - 日志解析（时间戳、级别、消息体提取）
    - 级别统计
    - 错误模式聚合与去重
    - 时间趋势分析
    """

    @property
    def name(self) -> str:
        return "log_analyzer"

    def get_capabilities(self) -> list[str]:
        return ["analyze_lines", "analyze_file", "analyze_container"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        dry_run = bool(args.get("dry_run", False))

        dispatch: dict[str, str] = {
            "analyze_lines": "_analyze_lines",
            "analyze_file": "_analyze_file",
            "analyze_container": "_analyze_container",
        }

        method_name = dispatch.get(action)
        if method_name is None:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would execute log_analyzer.{action}",
                simulated=True,
            )

        method = getattr(self, method_name)
        result: WorkerResult = await method(args)
        return result

    # ------------------------------------------------------------------
    # analyze_lines - 分析原始日志文本
    # ------------------------------------------------------------------
    async def _analyze_lines(self, args: dict[str, ArgValue]) -> WorkerResult:
        lines_raw = args.get("lines")
        if not isinstance(lines_raw, str):
            return WorkerResult(success=False, message="缺少参数: lines (日志文本)")

        source = str(args.get("source", "input"))
        top_n_raw = args.get("top_n", 10)
        top_n = int(top_n_raw) if isinstance(top_n_raw, (str, int)) else 10

        lines = lines_raw.strip().split("\n")
        analysis = self._do_analysis(lines, source, top_n)
        summary = self._format_summary(analysis)

        return WorkerResult(
            success=True,
            data=self._analysis_to_data(analysis),
            message=summary,
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # analyze_file - 从文件读取日志并分析
    # ------------------------------------------------------------------
    async def _analyze_file(self, args: dict[str, ArgValue]) -> WorkerResult:
        import asyncio
        from pathlib import Path

        path_raw = args.get("path")
        if not isinstance(path_raw, str):
            return WorkerResult(success=False, message="缺少参数: path (日志文件路径)")

        path = Path(path_raw).expanduser()
        if not path.exists():
            return WorkerResult(success=False, message=f"文件不存在: {path}")

        tail_raw = args.get("tail", 1000)
        tail_n = int(tail_raw) if isinstance(tail_raw, (str, int)) else 1000
        top_n_raw = args.get("top_n", 10)
        top_n = int(top_n_raw) if isinstance(top_n_raw, (str, int)) else 10

        def read_tail() -> list[str]:
            with open(path, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return all_lines[-tail_n:]

        lines = await asyncio.to_thread(read_tail)
        analysis = self._do_analysis(lines, str(path), top_n)
        summary = self._format_summary(analysis)

        return WorkerResult(
            success=True,
            data=self._analysis_to_data(analysis),
            message=summary,
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # analyze_container - 获取容器日志并分析
    # ------------------------------------------------------------------
    async def _analyze_container(self, args: dict[str, ArgValue]) -> WorkerResult:
        container_raw = args.get("container")
        if not isinstance(container_raw, str):
            return WorkerResult(success=False, message="缺少参数: container (容器名或ID)")

        tail_raw = args.get("tail", 500)
        tail_n = int(tail_raw) if isinstance(tail_raw, (str, int)) else 500
        top_n_raw = args.get("top_n", 10)
        top_n = int(top_n_raw) if isinstance(top_n_raw, (str, int)) else 10

        from src.workers.shell import ShellWorker

        shell = ShellWorker()
        result = await shell.execute(
            "execute_command",
            {"command": f"docker logs --tail {tail_n} {container_raw} 2>&1"},
        )

        if not result.success:
            return WorkerResult(
                success=False,
                message=f"获取容器日志失败: {result.message}",
            )

        raw_output = ""
        if result.data and isinstance(result.data, dict):
            raw_val = result.data.get("raw_output")
            if isinstance(raw_val, str):
                raw_output = raw_val
        if not raw_output:
            raw_output = result.message

        lines = raw_output.strip().split("\n")
        analysis = self._do_analysis(lines, f"container:{container_raw}", top_n)
        summary = self._format_summary(analysis)

        return WorkerResult(
            success=True,
            data=self._analysis_to_data(analysis),
            message=summary,
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # 核心分析逻辑
    # ------------------------------------------------------------------
    def _do_analysis(
        self, lines: list[str], source: str, top_n: int = 10
    ) -> LogAnalysis:
        entries = [self._parse_line(line.rstrip("\n")) for line in lines if line.strip()]

        # 级别计数
        level_counts: Counter[str] = Counter()
        for entry in entries:
            level_counts[entry.level] += 1

        # 模式聚合
        error_patterns: Counter[str] = Counter()
        warn_patterns: Counter[str] = Counter()
        pattern_samples: dict[str, str] = {}
        pattern_levels: dict[str, LogLevel] = {}

        for entry in entries:
            normalized = self._normalize_message(entry.message)
            if entry.level in _ERROR_LEVELS:
                error_patterns[normalized] += 1
                if normalized not in pattern_samples:
                    pattern_samples[normalized] = entry.raw
                    pattern_levels[normalized] = entry.level
            elif entry.level in _WARN_LEVELS:
                warn_patterns[normalized] += 1
                if normalized not in pattern_samples:
                    pattern_samples[normalized] = entry.raw
                    pattern_levels[normalized] = entry.level

        top_errors = [
            LogPatternCount(
                pattern=pat,
                count=cnt,
                sample=pattern_samples.get(pat, ""),
                level=pattern_levels.get(pat, "ERROR"),
            )
            for pat, cnt in error_patterns.most_common(top_n)
        ]

        top_warns = [
            LogPatternCount(
                pattern=pat,
                count=cnt,
                sample=pattern_samples.get(pat, ""),
                level=pattern_levels.get(pat, "WARN"),
            )
            for pat, cnt in warn_patterns.most_common(top_n)
        ]

        # 时间趋势
        trend = self._compute_trend(entries)

        # 去重统计
        all_patterns: set[str] = set()
        for entry in entries:
            all_patterns.add(self._normalize_message(entry.message))

        return LogAnalysis(
            total_lines=len(entries),
            level_counts=dict(level_counts),
            top_errors=top_errors,
            top_warns=top_warns,
            trend=trend,
            dedup_count=len(all_patterns),
            source=source,
        )

    # ------------------------------------------------------------------
    # 日志行解析
    # ------------------------------------------------------------------
    def _parse_line(self, line: str) -> LogEntry:
        timestamp = self._extract_timestamp(line)
        level = self._extract_level(line)
        message = self._extract_message(line, timestamp)

        return LogEntry(
            raw=line,
            timestamp=timestamp,
            level=level,
            message=message,
        )

    def _extract_timestamp(self, line: str) -> Optional[str]:
        for pattern in _TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(0)
        return None

    def _extract_level(self, line: str) -> LogLevel:
        upper_line = line.upper()
        for pattern, level in _LEVEL_PATTERNS:
            if re.search(pattern, upper_line):
                return level
        return "UNKNOWN"

    def _extract_message(self, line: str, timestamp: Optional[str]) -> str:
        msg = line
        if timestamp:
            idx = msg.find(timestamp)
            if idx >= 0:
                msg = msg[idx + len(timestamp):]

        # 去掉级别标记和前导分隔符
        for pattern, _ in _LEVEL_PATTERNS:
            msg = re.sub(pattern, "", msg, flags=re.IGNORECASE)
        msg = re.sub(r"^[\s\-\[\]|:]+", "", msg)
        return msg.strip()

    # ------------------------------------------------------------------
    # 消息归一化（用于去重聚合）
    # ------------------------------------------------------------------
    def _normalize_message(self, message: str) -> str:
        result = message
        for pattern, replacement in _NORMALIZE_RULES:
            result = re.sub(pattern, replacement, result)
        return result.strip()

    # ------------------------------------------------------------------
    # 时间趋势计算
    # ------------------------------------------------------------------
    def _compute_trend(self, entries: list[LogEntry]) -> list[LogTrendPoint]:
        time_buckets: defaultdict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "errors": 0, "warns": 0}
        )

        for entry in entries:
            ts = entry.timestamp
            if not ts:
                continue
            # 提取 HH:MM（5分钟窗口）
            time_match = re.search(r"(\d{2}):(\d{2})", ts)
            if not time_match:
                continue
            hour = time_match.group(1)
            minute = int(time_match.group(2))
            bucket_min = (minute // 5) * 5
            bucket_key = f"{hour}:{bucket_min:02d}"

            time_buckets[bucket_key]["total"] += 1
            if entry.level in _ERROR_LEVELS:
                time_buckets[bucket_key]["errors"] += 1
            elif entry.level in _WARN_LEVELS:
                time_buckets[bucket_key]["warns"] += 1

        if not time_buckets:
            return []

        sorted_keys = sorted(time_buckets.keys())
        return [
            LogTrendPoint(
                window=key,
                total=time_buckets[key]["total"],
                errors=time_buckets[key]["errors"],
                warns=time_buckets[key]["warns"],
            )
            for key in sorted_keys
        ]

    # ------------------------------------------------------------------
    # 格式化输出
    # ------------------------------------------------------------------
    def _format_summary(self, analysis: LogAnalysis) -> str:
        lines: list[str] = []
        lines.append(f"日志分析 ({analysis.source})")
        lines.append(f"  总行数: {analysis.total_lines}, 独立模式: {analysis.dedup_count}")

        # 级别分布
        if analysis.level_counts:
            level_parts: list[str] = []
            for level in ["FATAL", "ERROR", "WARN", "INFO", "DEBUG", "UNKNOWN"]:
                count = analysis.level_counts.get(level, 0)
                if count > 0:
                    pct = count / max(analysis.total_lines, 1) * 100
                    level_parts.append(f"{level}: {count} ({pct:.1f}%)")
            lines.append(f"  级别分布: {', '.join(level_parts)}")

        # Top 错误
        if analysis.top_errors:
            lines.append(f"  Top {len(analysis.top_errors)} 错误:")
            for i, err in enumerate(analysis.top_errors[:5], 1):
                lines.append(f"    {i}. [{err.count}次] {err.pattern[:80]}")

        # Top 警告
        if analysis.top_warns:
            lines.append(f"  Top {len(analysis.top_warns)} 警告:")
            for i, warn in enumerate(analysis.top_warns[:3], 1):
                lines.append(f"    {i}. [{warn.count}次] {warn.pattern[:80]}")

        # 趋势异常检测
        if analysis.trend:
            avg_errors = sum(p.errors for p in analysis.trend) / max(len(analysis.trend), 1)
            spikes = [
                p for p in analysis.trend if p.errors > avg_errors * 3 and p.errors >= 3
            ]
            if spikes:
                spike_str = ", ".join(f"{s.window}({s.errors}次)" for s in spikes[:3])
                lines.append(f"  异常峰值: {spike_str}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 分析结果转 data 字段
    # ------------------------------------------------------------------
    def _analysis_to_data(
        self, analysis: LogAnalysis
    ) -> list[dict[str, Union[str, int]]]:
        """将分析结果转为 WorkerResult.data 兼容格式"""
        rows: list[dict[str, Union[str, int]]] = []

        # 概览行
        rows.append({
            "name": "summary",
            "total_lines": analysis.total_lines,
            "dedup_count": analysis.dedup_count,
            "source": analysis.source,
        })

        # 级别计数
        for level, count in analysis.level_counts.items():
            rows.append({"name": f"level_{level}", "count": count})

        # Top 错误
        for i, err in enumerate(analysis.top_errors[:10]):
            rows.append({
                "name": f"error_{i}",
                "pattern": err.pattern[:100],
                "count": err.count,
            })

        return rows
