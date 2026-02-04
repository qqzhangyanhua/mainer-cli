"""ReAct 引擎测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.manager import OpsAIConfig
from src.orchestrator.engine import OrchestratorEngine
from src.types import Instruction, WorkerResult


class TestOrchestratorEngine:
    """测试 Orchestrator 引擎"""

    @pytest.fixture
    def engine(self) -> OrchestratorEngine:
        """创建测试引擎"""
        config = OpsAIConfig()
        return OrchestratorEngine(config)

    def test_get_worker(self, engine: OrchestratorEngine) -> None:
        """测试获取 Worker"""
        worker = engine.get_worker("system")
        assert worker is not None
        assert worker.name == "system"

    def test_get_worker_unknown(self, engine: OrchestratorEngine) -> None:
        """测试获取未知 Worker"""
        worker = engine.get_worker("unknown")
        assert worker is None

    @pytest.mark.asyncio
    async def test_execute_instruction_safe(self, engine: OrchestratorEngine) -> None:
        """测试执行安全指令"""
        instruction = Instruction(
            worker="system",
            action="check_disk_usage",
            args={"path": "/"},
        )

        result = await engine.execute_instruction(instruction)

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_execute_instruction_unknown_worker(
        self, engine: OrchestratorEngine
    ) -> None:
        """测试执行未知 Worker 指令"""
        instruction = Instruction(
            worker="unknown",
            action="test",
            args={},
        )

        result = await engine.execute_instruction(instruction)

        assert result.success is False
        assert "Unknown worker" in result.message

    @pytest.mark.asyncio
    async def test_react_loop_single_step(self, engine: OrchestratorEngine) -> None:
        """测试单步 ReAct 循环"""
        # Mock LLM 响应
        mock_llm_response = '{"worker": "system", "action": "check_disk_usage", "args": {"path": "/"}, "risk_level": "safe"}'

        with patch.object(
            engine._llm_client, "generate", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = mock_llm_response

            # Mock task_completed
            with patch.object(
                engine, "execute_instruction", new_callable=AsyncMock
            ) as mock_execute:
                mock_execute.return_value = WorkerResult(
                    success=True,
                    data={"percent_used": 50},
                    message="Disk 50% used",
                    task_completed=True,
                )

                result = await engine.react_loop("检查磁盘")

                assert "Disk 50% used" in result
                mock_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_react_loop_max_iterations(self, engine: OrchestratorEngine) -> None:
        """测试 ReAct 循环最大迭代"""
        mock_llm_response = '{"worker": "system", "action": "check_disk_usage", "args": {}, "risk_level": "safe"}'

        with patch.object(
            engine._llm_client, "generate", new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = mock_llm_response

            with patch.object(
                engine, "execute_instruction", new_callable=AsyncMock
            ) as mock_execute:
                # 永远不完成
                mock_execute.return_value = WorkerResult(
                    success=True,
                    message="Still working",
                    task_completed=False,
                )

                result = await engine.react_loop("无限任务")

                # 应该在最大迭代后停止
                assert mock_generate.call_count == 5  # 默认 max_iterations
