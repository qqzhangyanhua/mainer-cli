"""Worker 基类测试"""

from __future__ import annotations

import pytest

from src.types import WorkerResult
from src.workers.base import BaseWorker


class MockWorker(BaseWorker):
    """测试用 Mock Worker"""

    @property
    def name(self) -> str:
        return "mock"

    def get_capabilities(self) -> list[str]:
        return ["test_action", "another_action"]

    async def execute(self, action: str, args: dict[str, str | int | bool | list[str] | dict[str, str]]) -> WorkerResult:
        if action == "test_action":
            return WorkerResult(
                success=True,
                data={"result": "test"},
                message="Test completed",
                task_completed=True,
            )
        return WorkerResult(
            success=False,
            message=f"Unknown action: {action}",
        )


class TestBaseWorker:
    """测试 Worker 基类"""

    def test_worker_has_name(self) -> None:
        """测试 Worker 有名称"""
        worker = MockWorker()
        assert worker.name == "mock"

    def test_worker_has_capabilities(self) -> None:
        """测试 Worker 有能力列表"""
        worker = MockWorker()
        caps = worker.get_capabilities()
        assert "test_action" in caps
        assert "another_action" in caps

    @pytest.mark.asyncio
    async def test_worker_execute_success(self) -> None:
        """测试 Worker 执行成功"""
        worker = MockWorker()
        result = await worker.execute("test_action", {})

        assert result.success is True
        assert result.task_completed is True
        assert result.message == "Test completed"

    @pytest.mark.asyncio
    async def test_worker_execute_unknown_action(self) -> None:
        """测试 Worker 执行未知动作"""
        worker = MockWorker()
        result = await worker.execute("unknown", {})

        assert result.success is False
        assert "Unknown action" in result.message
