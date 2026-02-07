"""Shell Worker 测试"""

import pytest

from src.workers.shell import (
    MAX_OUTPUT_LENGTH,
    TRUNCATE_HEAD,
    TRUNCATE_TAIL,
    ShellWorker,
)


class TestShellWorker:
    """测试 Shell Worker"""

    def test_worker_name(self) -> None:
        """测试 Worker 名称"""
        worker = ShellWorker()
        assert worker.name == "shell"

    def test_capabilities(self) -> None:
        """测试能力列表"""
        worker = ShellWorker()
        assert worker.get_capabilities() == ["execute_command"]

    @pytest.mark.asyncio
    async def test_execute_command_success(self) -> None:
        """测试执行成功的命令"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo 'Hello World'"},
        )

        assert result.success is True
        assert result.task_completed is True
        assert "Hello World" in result.message

    @pytest.mark.asyncio
    async def test_execute_command_dry_run(self) -> None:
        """测试 dry-run 模式（使用白名单内的命令）"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "ls -la /tmp", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "ls -la /tmp" in result.message

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self) -> None:
        """测试危险命令被阻止"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "rm -rf /", "dry_run": True},
        )

        assert result.success is False
        assert "blocked" in result.message.lower()
        assert result.data is not None
        assert result.data.get("blocked") is True

    @pytest.mark.asyncio
    async def test_command_not_in_whitelist_blocked(self) -> None:
        """测试不在白名单内的命令被阻止"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "my-custom-script.sh"},
        )

        assert result.success is False
        assert "not in whitelist" in result.message.lower()

    @pytest.mark.asyncio
    async def test_command_chaining_blocked(self) -> None:
        """测试命令链接被阻止"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "ls && rm -rf /"},
        )

        assert result.success is False
        assert "&&" in result.message or "dangerous" in result.message.lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知 action"""
        worker = ShellWorker()
        result = await worker.execute("unknown", {})

        assert result.success is False
        assert "Unknown action" in result.message

    @pytest.mark.asyncio
    async def test_execute_command_returns_raw_output(self) -> None:
        """测试返回值包含 raw_output 字段"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo 'test output'"},
        )

        assert result.success is True
        assert result.data is not None
        assert isinstance(result.data, dict)
        assert "raw_output" in result.data
        assert "truncated" in result.data
        assert "test output" in str(result.data["raw_output"])
        assert result.data["truncated"] is False

    def test_truncate_output_short(self) -> None:
        """测试短输出不被截断"""
        worker = ShellWorker()
        short_output = "a" * 100
        result, truncated = worker._truncate_output(short_output)

        assert result == short_output
        assert truncated is False

    def test_truncate_output_exact_limit(self) -> None:
        """测试刚好达到限制的输出不被截断"""
        worker = ShellWorker()
        exact_output = "a" * MAX_OUTPUT_LENGTH
        result, truncated = worker._truncate_output(exact_output)

        assert result == exact_output
        assert truncated is False

    def test_truncate_output_long(self) -> None:
        """测试超长输出被正确截断"""
        worker = ShellWorker()
        long_output = "a" * 10000
        result, truncated = worker._truncate_output(long_output)

        assert truncated is True
        assert len(result) < len(long_output)
        assert "truncated" in result
        # 验证头尾部分被保留
        assert result.startswith("a" * TRUNCATE_HEAD)
        assert result.endswith("a" * TRUNCATE_TAIL)

    def test_truncate_preserves_head_tail(self) -> None:
        """测试截断保留头尾内容"""
        worker = ShellWorker()
        # 创建有明确头尾的长输出
        head_marker = "HEAD_START_" + "x" * (TRUNCATE_HEAD - 11)
        tail_marker = "y" * (TRUNCATE_TAIL - 9) + "_TAIL_END"
        middle = "m" * 5000
        long_output = head_marker + middle + tail_marker

        result, truncated = worker._truncate_output(long_output)

        assert truncated is True
        assert "HEAD_START_" in result
        assert "_TAIL_END" in result
        # 中间部分应该被截断
        assert "m" * 100 not in result or result.count("m") < 5000
