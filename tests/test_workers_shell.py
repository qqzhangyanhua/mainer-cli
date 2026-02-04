"""Shell Worker 测试"""

import pytest

from src.workers.shell import ShellWorker


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
        """测试 dry-run 模式"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "rm -rf /", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "rm -rf /" in result.message

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知 action"""
        worker = ShellWorker()
        result = await worker.execute("unknown", {})

        assert result.success is False
        assert "Unknown action" in result.message
