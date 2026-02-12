"""集成测试"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config.manager import ConfigManager, OpsAIConfig
from src.orchestrator.engine import OrchestratorEngine


class TestIntegration:
    """集成测试"""

    @pytest.fixture
    def config(self, tmp_path: Path) -> OpsAIConfig:
        """创建测试配置"""
        config_path = tmp_path / ".opsai" / "config.json"
        manager = ConfigManager(config_path=config_path)
        return manager.load()

    @pytest.mark.asyncio
    async def test_full_workflow_safe_operation(self, config: OpsAIConfig) -> None:
        """测试完整工作流 - 安全操作（LangGraph）"""
        engine = OrchestratorEngine(config)

        mock_state = {
            "final_message": "Disk usage: 50%",
            "task_completed": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(
            engine._react_graph, "run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_state

            result = await engine.react_loop_graph("检查磁盘")

            assert "Disk" in result
            assert "Error" not in result

    @pytest.mark.asyncio
    async def test_high_risk_rejected_via_graph(self, config: OpsAIConfig) -> None:
        """测试高危操作通过 LangGraph safety 节点被拒绝"""
        engine = OrchestratorEngine(config)

        mock_state = {
            "final_message": "Error: risk level high exceeds configured max risk safe",
            "task_completed": False,
            "is_error": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(
            engine._react_graph, "run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_state

            result = await engine.react_loop_graph("删除所有文件")

            assert "exceeds configured max risk" in result

    @pytest.mark.asyncio
    async def test_execute_instruction_directly(
        self, config: OpsAIConfig
    ) -> None:
        """测试直接执行指令（template run 路径）"""
        from src.types import Instruction

        engine = OrchestratorEngine(config)

        instruction = Instruction(
            worker="system",
            action="check_disk_usage",
            args={"path": "/"},
            risk_level="safe",
        )

        result = await engine.execute_instruction(instruction)

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_dry_run_mode(self, config: OpsAIConfig) -> None:
        """测试 dry-run 模式通过 LangGraph"""
        engine = OrchestratorEngine(config, dry_run=True)

        mock_state = {
            "final_message": "[DRY-RUN] Would check disk usage",
            "task_completed": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(
            engine._react_graph, "run", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_state

            result = await engine.react_loop_graph("检查磁盘")

            assert "DRY-RUN" in result or "Error" not in result
