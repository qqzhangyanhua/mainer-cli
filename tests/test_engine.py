"""ReAct 引擎测试"""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.manager import OpsAIConfig
from src.orchestrator.engine import OrchestratorEngine
from src.types import Instruction


class TestOrchestratorEngine:
    """测试 Orchestrator 引擎"""

    @pytest.fixture
    def engine(self) -> OrchestratorEngine:
        """创建测试引擎"""
        config = OpsAIConfig()
        config.performance.enable_command_cache = False
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

    @pytest.mark.asyncio
    async def test_cache_hit_safe_command(self) -> None:
        """测试缓存命中安全命令（无需审批）"""
        config = OpsAIConfig()
        config.performance.enable_command_cache = True
        config.performance.cache_confidence_threshold = 0.8
        engine = OrchestratorEngine(config)

        result = await engine.react_loop_graph("查看磁盘使用情况")

        assert result is not None
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_cache_hit_high_risk_requires_approval(self) -> None:
        """测试缓存命中高风险命令需要审批"""
        config = OpsAIConfig()
        config.performance.enable_command_cache = True
        config.performance.cache_confidence_threshold = 0.8
        config.safety.auto_approve_safe = False

        approval_called = False

        def mock_confirmation(instruction: Instruction, risk_level: str) -> bool:
            nonlocal approval_called
            approval_called = True
            return False  # 拒绝执行

        engine = OrchestratorEngine(config, confirmation_callback=mock_confirmation)

        # 添加一个高风险命令模式到缓存
        from src.orchestrator.command_cache import CommandPattern

        high_risk_pattern = CommandPattern(
            pattern=r"^删除所有文件$",
            worker="system",
            action="delete_files",
            risk_level="high",
            confidence=0.9,
        )
        engine._command_cache.add_pattern(high_risk_pattern)

        result = await engine.react_loop_graph("删除所有文件")

        assert approval_called, "高风险命令应该触发审批回调"
        assert result == "Operation cancelled by user"

    @pytest.mark.asyncio
    async def test_cache_hit_medium_risk_with_approval(self) -> None:
        """测试缓存命中中等风险命令通过审批后执行"""
        config = OpsAIConfig()
        config.performance.enable_command_cache = True
        config.performance.cache_confidence_threshold = 0.8
        config.safety.auto_approve_safe = False

        approval_called = False

        def mock_confirmation(instruction: Instruction, risk_level: str) -> bool:
            nonlocal approval_called
            approval_called = True
            return True  # 批准执行

        engine = OrchestratorEngine(config, confirmation_callback=mock_confirmation)

        # 添加一个中等风险命令模式到缓存
        from src.orchestrator.command_cache import CommandPattern

        medium_risk_pattern = CommandPattern(
            pattern=r"^重启容器$",
            worker="container",
            action="restart",
            risk_level="medium",
            confidence=0.9,
        )
        engine._command_cache.add_pattern(medium_risk_pattern)

        result = await engine.react_loop_graph("重启容器")

        assert approval_called, "中等风险命令应该触发审批回调"
        assert result != "Operation cancelled by user"
