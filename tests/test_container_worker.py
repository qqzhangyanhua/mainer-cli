"""ContainerWorker 测试（基于 shell 命令）"""

import pytest

from src.workers.container import ContainerWorker


class TestContainerWorker:
    """ContainerWorker 测试类"""

    @pytest.fixture
    def worker(self) -> ContainerWorker:
        """创建 ContainerWorker 实例"""
        return ContainerWorker()

    def test_name(self, worker: ContainerWorker) -> None:
        """测试 worker 名称"""
        assert worker.name == "container"

    def test_capabilities(self, worker: ContainerWorker) -> None:
        """测试 worker 能力列表"""
        capabilities = worker.get_capabilities()
        assert "list_containers" in capabilities
        assert "inspect_container" in capabilities
        assert "logs" in capabilities
        assert "restart" in capabilities
        assert "stop" in capabilities
        assert "start" in capabilities
        assert "stats" in capabilities

    @pytest.mark.asyncio
    async def test_list_containers_dry_run(self, worker: ContainerWorker) -> None:
        """测试 dry-run 模式列出容器"""
        result = await worker.execute(
            "list_containers",
            {"all": False, "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_inspect_container_dry_run(self, worker: ContainerWorker) -> None:
        """测试 dry-run 模式查看容器"""
        result = await worker.execute(
            "inspect_container",
            {"container_id": "test-container", "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_restart_dry_run(self, worker: ContainerWorker) -> None:
        """测试 dry-run 模式重启容器"""
        result = await worker.execute(
            "restart",
            {"container_id": "test-container", "dry_run": True},
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_unknown_action(self, worker: ContainerWorker) -> None:
        """测试未知动作"""
        result = await worker.execute("unknown_action", {})
        assert result.success is False
        assert "Unknown action" in result.message
