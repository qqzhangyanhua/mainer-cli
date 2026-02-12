"""ReAct 引擎测试"""

from unittest.mock import AsyncMock, patch

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
    async def test_execute_instruction_unknown_worker(self, engine: OrchestratorEngine) -> None:
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
    async def test_react_loop_graph_single_step(self, engine: OrchestratorEngine) -> None:
        """测试单步 ReAct 循环（LangGraph）"""
        mock_state = {
            "final_message": "Disk 50% used",
            "task_completed": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(engine._react_graph, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_state

            result = await engine.react_loop_graph("检查磁盘")

            assert result == "Disk 50% used"
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_react_loop_graph_max_iterations(self, engine: OrchestratorEngine) -> None:
        """测试 ReAct 循环最大迭代（LangGraph）"""
        mock_state = {
            "final_message": "Task incomplete: reached maximum iterations",
            "task_completed": False,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(engine._react_graph, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_state

            await engine.react_loop_graph("无限任务", max_iterations=5)

            mock_run.assert_called_once()
            # max_iterations 被传递到 ReactGraph.run
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["max_iterations"] == 5

    @pytest.mark.asyncio
    async def test_react_loop_graph_approval_required(self, engine: OrchestratorEngine) -> None:
        """测试 LangGraph 返回审批中断"""
        mock_state = {
            "needs_approval": True,
            "approval_granted": False,
            "messages": [],
        }

        with patch.object(engine._react_graph, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_state

            result = await engine.react_loop_graph("高危操作")

            assert result == "__APPROVAL_REQUIRED__"

    @pytest.mark.asyncio
    async def test_react_loop_graph_error_handling(self, engine: OrchestratorEngine) -> None:
        """测试 LangGraph 错误处理"""
        with patch.object(engine._react_graph, "run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("graph failed")

            result = await engine.react_loop_graph("测试错误")

            assert "Error in ReactGraph" in result

    @pytest.mark.asyncio
    async def test_react_loop_graph_updates_session_history(
        self, engine: OrchestratorEngine
    ) -> None:
        """测试 react_loop_graph 更新会话历史"""
        mock_state = {
            "final_message": "ok",
            "task_completed": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(engine._react_graph, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_state

            history = []
            result = await engine.react_loop_graph("测试", session_history=history)

            assert result == "ok"

    @pytest.mark.asyncio
    async def test_resume_react_loop(self, engine: OrchestratorEngine) -> None:
        """测试恢复被中断的 ReAct 循环"""
        mock_state = {
            "final_message": "Resumed ok",
            "task_completed": True,
            "needs_approval": False,
            "messages": [],
        }

        with patch.object(engine._react_graph, "resume", new_callable=AsyncMock) as mock_resume:
            mock_resume.return_value = mock_state

            result = await engine.resume_react_loop("session-1", approval_granted=True)

            assert result == "Resumed ok"
            mock_resume.assert_called_once_with(
                session_id="session-1",
                approval_granted=True,
            )
