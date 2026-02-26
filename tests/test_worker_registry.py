"""WorkerRegistry 测试"""

from pathlib import Path

from src.config.manager import WorkersConfig
from src.workers.registry import WorkerRegistry
from src.workers.system import SystemWorker


class TestWorkerRegistry:
    """测试 Worker 注册与插件加载"""

    def test_registry_respects_disabled(self) -> None:
        config = WorkersConfig(disabled=["system"])
        registry = WorkerRegistry(config)
        registry.register(SystemWorker())
        assert "system" not in registry.workers

    def test_load_plugin_worker(self, tmp_path: Path) -> None:
        plugin_path = tmp_path / "demo_worker.py"
        plugin_path.write_text(
            """
from __future__ import annotations

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class DemoWorker(BaseWorker):
    @property
    def name(self) -> str:
        return "demo"

    def get_capabilities(self) -> list[str]:
        return ["ping"]

    async def execute(self, action: str, args: dict[str, ArgValue]) -> WorkerResult:
        return WorkerResult(success=True, message="pong")
""",
            encoding="utf-8",
        )

        config = WorkersConfig(plugin_paths=[str(plugin_path)])
        registry = WorkerRegistry(config)
        registry.load_plugins()

        assert "demo" in registry.workers
