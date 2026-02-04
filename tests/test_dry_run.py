"""Dry-run 模式测试"""

import pytest

from src.workers.system import SystemWorker


class TestDryRun:
    """Dry-run 模式测试类"""

    @pytest.fixture
    def worker(self) -> SystemWorker:
        """创建 SystemWorker 实例"""
        return SystemWorker()

    @pytest.mark.asyncio
    async def test_find_large_files_dry_run(self, worker: SystemWorker) -> None:
        """测试 dry-run 模式查找大文件"""
        result = await worker.execute(
            "find_large_files",
            {"path": "/tmp", "min_size_mb": 100, "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_check_disk_usage_dry_run(self, worker: SystemWorker) -> None:
        """测试 dry-run 模式检查磁盘使用"""
        result = await worker.execute(
            "check_disk_usage",
            {"path": "/", "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_delete_files_dry_run(self, worker: SystemWorker) -> None:
        """测试 dry-run 模式删除文件"""
        result = await worker.execute(
            "delete_files",
            {"files": ["/tmp/test1.txt", "/tmp/test2.txt"], "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "Would delete 2 files" in result.message

    @pytest.mark.asyncio
    async def test_normal_execution_not_simulated(self, worker: SystemWorker) -> None:
        """测试正常执行不标记为模拟"""
        result = await worker.execute(
            "check_disk_usage",
            {"path": "/"},
        )
        # 正常执行不应该标记为 simulated
        assert result.simulated is False
