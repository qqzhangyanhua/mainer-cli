"""LogAnalyzerWorker 单元测试"""

from __future__ import annotations

import pytest

from src.workers.log_analyzer import LogAnalyzerWorker


@pytest.fixture
def worker() -> LogAnalyzerWorker:
    return LogAnalyzerWorker()


# ------------------------------------------------------------------
# 基本属性
# ------------------------------------------------------------------

def test_name(worker: LogAnalyzerWorker) -> None:
    assert worker.name == "log_analyzer"


def test_capabilities(worker: LogAnalyzerWorker) -> None:
    caps = worker.get_capabilities()
    assert "analyze_lines" in caps
    assert "analyze_file" in caps
    assert "analyze_container" in caps


# ------------------------------------------------------------------
# analyze_lines
# ------------------------------------------------------------------

SAMPLE_LOGS = """2024-01-15T09:30:01Z INFO  Server started on port 8080
2024-01-15T09:30:02Z INFO  Database connected
2024-01-15T09:30:10Z WARN  High memory usage detected: 82%
2024-01-15T09:30:15Z ERROR Connection timeout to redis:6379
2024-01-15T09:30:16Z ERROR Connection timeout to redis:6379
2024-01-15T09:30:17Z ERROR Connection timeout to redis:6379
2024-01-15T09:30:20Z INFO  Request processed in 120ms
2024-01-15T09:30:25Z ERROR  NullPointerException at line 42
2024-01-15T09:30:30Z WARN  Slow query detected: 2500ms
2024-01-15T09:30:35Z INFO  Health check OK
2024-01-15T09:31:00Z FATAL Out of memory
"""


@pytest.mark.asyncio
async def test_analyze_lines_basic(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {"lines": SAMPLE_LOGS})
    assert result.success is True
    assert result.task_completed is True
    assert "日志分析" in result.message


@pytest.mark.asyncio
async def test_analyze_lines_level_counts(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {"lines": SAMPLE_LOGS})
    assert result.success is True
    assert isinstance(result.data, list)

    # 找到级别计数
    level_data = {
        r["name"]: r["count"]
        for r in result.data
        if isinstance(r, dict) and str(r.get("name", "")).startswith("level_")
    }
    assert level_data.get("level_ERROR") == 4
    assert level_data.get("level_WARN") == 2
    assert level_data.get("level_INFO") == 4
    assert level_data.get("level_FATAL") == 1


@pytest.mark.asyncio
async def test_analyze_lines_error_patterns(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {"lines": SAMPLE_LOGS})
    assert result.success is True
    assert isinstance(result.data, list)

    error_data = [
        r for r in result.data
        if isinstance(r, dict) and str(r.get("name", "")).startswith("error_")
    ]
    # 至少有错误模式
    assert len(error_data) >= 1
    # Connection timeout 出现 3 次，应该是 top 错误
    top_error = error_data[0]
    assert top_error["count"] == 3


@pytest.mark.asyncio
async def test_analyze_lines_trend(worker: LogAnalyzerWorker) -> None:
    """测试趋势计算 - 所有日志在 09:30 窗口"""
    result = await worker.execute("analyze_lines", {"lines": SAMPLE_LOGS})
    assert result.success is True
    assert "09:30" in result.message or "总行数" in result.message


@pytest.mark.asyncio
async def test_analyze_lines_missing_param(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {})
    assert result.success is False
    assert "缺少参数" in result.message


@pytest.mark.asyncio
async def test_analyze_lines_empty(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {"lines": ""})
    assert result.success is True
    assert "总行数: 0" in result.message


# ------------------------------------------------------------------
# 日志解析细节
# ------------------------------------------------------------------

def test_parse_line_iso_timestamp(worker: LogAnalyzerWorker) -> None:
    entry = worker._parse_line("2024-01-15T09:30:45.123Z ERROR Something broke")
    assert entry.timestamp == "2024-01-15T09:30:45.123Z"
    assert entry.level == "ERROR"
    assert "broke" in entry.message


def test_parse_line_syslog_format(worker: LogAnalyzerWorker) -> None:
    entry = worker._parse_line("Jan 15 09:30:45 myhost sshd[1234]: Connection from 10.0.0.1")
    assert entry.timestamp == "Jan 15 09:30:45"
    assert entry.level == "UNKNOWN"


def test_parse_line_nginx_error(worker: LogAnalyzerWorker) -> None:
    entry = worker._parse_line(
        '2024/01/15 09:30:45 [error] 1234#0: *5678 upstream timed out'
    )
    assert entry.level == "ERROR"


def test_parse_line_warn_level(worker: LogAnalyzerWorker) -> None:
    entry = worker._parse_line("2024-01-15 09:30:45 WARNING Disk almost full")
    assert entry.level == "WARN"


def test_parse_line_no_timestamp(worker: LogAnalyzerWorker) -> None:
    entry = worker._parse_line("ERROR: something failed")
    assert entry.timestamp is None
    assert entry.level == "ERROR"


# ------------------------------------------------------------------
# 消息归一化
# ------------------------------------------------------------------

def test_normalize_ips(worker: LogAnalyzerWorker) -> None:
    result = worker._normalize_message("Connection from 192.168.1.100 port 22")
    assert "<IP>" in result
    assert "192.168.1.100" not in result


def test_normalize_numbers(worker: LogAnalyzerWorker) -> None:
    result = worker._normalize_message("Process 12345 exited with code 1")
    assert "<N>" in result
    assert "12345" not in result


def test_normalize_hex_ids(worker: LogAnalyzerWorker) -> None:
    result = worker._normalize_message("container abc123def456 stopped")
    assert "<HEX>" in result


def test_normalize_uuid(worker: LogAnalyzerWorker) -> None:
    result = worker._normalize_message("request 550e8400-e29b-41d4-a716-446655440000 failed")
    assert "<UUID>" in result


# ------------------------------------------------------------------
# dry-run 和未知 action
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_lines", {"lines": "test", "dry_run": True})
    assert result.success is True
    assert result.simulated is True
    assert "DRY-RUN" in result.message


@pytest.mark.asyncio
async def test_unknown_action(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("nonexistent", {})
    assert result.success is False
    assert "Unknown action" in result.message


# ------------------------------------------------------------------
# analyze_file
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_file(worker: LogAnalyzerWorker, tmp_path: object) -> None:
    """测试文件分析"""
    from pathlib import Path
    log_file = Path(str(tmp_path)) / "test.log"
    log_file.write_text(SAMPLE_LOGS, encoding="utf-8")

    result = await worker.execute("analyze_file", {"path": str(log_file)})
    assert result.success is True
    assert "日志分析" in result.message


@pytest.mark.asyncio
async def test_analyze_file_not_found(worker: LogAnalyzerWorker) -> None:
    result = await worker.execute("analyze_file", {"path": "/nonexistent/file.log"})
    assert result.success is False
    assert "不存在" in result.message


# ------------------------------------------------------------------
# 大量重复日志去重
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_repeated_errors(worker: LogAnalyzerWorker) -> None:
    """100 行相同的错误应该聚合为 1 个模式"""
    lines = "\n".join(
        f"2024-01-15T09:{i // 60:02d}:{i % 60:02d}Z ERROR Connection timeout to db:5432"
        for i in range(100)
    )
    result = await worker.execute("analyze_lines", {"lines": lines})
    assert result.success is True
    assert isinstance(result.data, list)

    error_rows = [
        r for r in result.data
        if isinstance(r, dict) and str(r.get("name", "")).startswith("error_")
    ]
    # 所有 100 条聚合为 1 个模式
    assert len(error_rows) == 1
    assert error_rows[0]["count"] == 100
