"""ReAct Graph 测试"""

from __future__ import annotations

import pytest

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.graph.checkpoint import SQLITE_AVAILABLE
from src.orchestrator.graph import ReactGraph
from src.orchestrator.graph.react_nodes import ReactNodes
from src.workers.audit import AuditWorker
from src.workers.base import BaseWorker
from src.workers.system import SystemWorker


class MockLLMClient(LLMClient):
    """Mock LLM 客户端，用于测试"""

    def __init__(self) -> None:
        """初始化 Mock 客户端"""
        # 不调用父类 __init__，避免依赖配置
        pass

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[object] | None = None,
    ) -> str:
        """生成响应（模拟）"""
        # 返回一个简单的 chat 指令
        return """```json
{
    "worker": "chat",
    "action": "greet",
    "args": {},
    "risk_level": "safe"
}
```"""

    def parse_json_response(self, response: str) -> dict[str, object] | None:
        """解析 JSON 响应（模拟）"""
        return {
            "worker": "chat",
            "action": "greet",
            "args": {},
            "risk_level": "safe",
        }


class TestReactGraph:
    """ReactGraph 基础测试"""

    @pytest.fixture
    def mock_llm(self) -> MockLLMClient:
        """Mock LLM 客户端"""
        return MockLLMClient()

    @pytest.fixture
    def workers(self) -> dict[str, BaseWorker]:
        """Worker 池"""
        return {
            "system": SystemWorker(),
            "audit": AuditWorker(),
        }

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        """环境上下文"""
        return EnvironmentContext()

    @pytest.fixture
    def react_graph(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> ReactGraph:
        """ReactGraph 实例"""
        return ReactGraph(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=True,
            enable_checkpoints=True,
            enable_interrupts=False,  # 测试时不启用 interrupt
            use_sqlite=False,  # 使用内存存储
        )

    async def test_graph_initialization(self, react_graph: ReactGraph) -> None:
        """测试 Graph 初始化"""
        assert react_graph is not None

    async def test_get_mermaid_diagram(self, react_graph: ReactGraph) -> None:
        """测试生成 Mermaid 图表"""
        diagram = react_graph.get_mermaid_diagram()
        assert diagram is not None
        assert len(diagram) > 0
        # 检查包含关键节点
        assert "preprocess" in diagram
        assert "reason" in diagram
        assert "execute" in diagram


@pytest.mark.skipif(not SQLITE_AVAILABLE, reason="langgraph sqlite checkpoint not installed")
class TestReactGraphWithSQLite:
    """ReactGraph SQLite 持久化测试"""

    @pytest.fixture
    def mock_llm(self) -> MockLLMClient:
        """Mock LLM 客户端"""
        return MockLLMClient()

    @pytest.fixture
    def workers(self) -> dict[str, BaseWorker]:
        """Worker 池"""
        return {
            "system": SystemWorker(),
            "audit": AuditWorker(),
        }

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        """环境上下文"""
        return EnvironmentContext()

    @pytest.fixture
    def react_graph_sqlite(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
        tmp_path: object,
    ) -> ReactGraph:
        """ReactGraph 实例（SQLite 模式）"""
        from pathlib import Path

        db_path = Path(str(tmp_path)) / "test_checkpoints.db"
        return ReactGraph(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=True,
            enable_checkpoints=True,
            enable_interrupts=False,
            use_sqlite=True,
            checkpoint_db_path=db_path,
        )

    async def test_sqlite_graph_initialization(self, react_graph_sqlite: ReactGraph) -> None:
        """测试 SQLite Graph 初始化"""
        assert react_graph_sqlite is not None


class TestReactGraphStateManagement:
    """ReactGraph 状态管理测试"""

    @pytest.fixture
    def mock_llm(self) -> MockLLMClient:
        """Mock LLM 客户端"""
        return MockLLMClient()

    @pytest.fixture
    def workers(self) -> dict[str, BaseWorker]:
        """Worker 池"""
        return {
            "system": SystemWorker(),
            "audit": AuditWorker(),
        }

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        """环境上下文"""
        return EnvironmentContext()

    @pytest.fixture
    def react_graph(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> ReactGraph:
        """ReactGraph 实例"""
        return ReactGraph(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=True,
            enable_checkpoints=True,
            enable_interrupts=False,
        )

    async def test_get_nonexistent_state_returns_empty(self, react_graph: ReactGraph) -> None:
        """测试获取不存在的会话状态"""
        state = react_graph.get_state("nonexistent_session")
        # LangGraph 对于不存在的会话返回空字典
        assert state is not None
        assert isinstance(state, dict)


class TestReactNodesSafetyPolicy:
    """ReactNodes 安全策略测试"""

    @pytest.fixture
    def mock_llm(self) -> MockLLMClient:
        """Mock LLM 客户端"""
        return MockLLMClient()

    @pytest.fixture
    def workers(self) -> dict[str, BaseWorker]:
        """Worker 池"""
        return {
            "system": SystemWorker(),
            "audit": AuditWorker(),
        }

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        """环境上下文"""
        return EnvironmentContext()

    @pytest.mark.asyncio
    async def test_high_risk_goes_to_approval_in_graph_mode(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> None:
        """测试高危操作进入审批流程而非直接阻止"""
        nodes = ReactNodes(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=False,
            max_risk="high",
            auto_approve_safe=True,
            require_dry_run_for_high_risk=True,
        )

        state = {
            "current_instruction": {
                "worker": "system",
                "action": "delete_files",
                "args": {"files": ["tmp.txt"]},
                "risk_level": "high",
                "dry_run": False,
            },
            "is_simple_intent": False,
        }

        result = await nodes.safety_node(state)

        # 高危操作应进入审批流程，而非报错
        assert result.get("is_error") is None
        assert result.get("risk_level") == "high"
        assert result.get("needs_approval") is True

    @pytest.mark.asyncio
    async def test_high_risk_with_instruction_dry_run_allowed(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> None:
        """测试指令自带 dry_run 时高危操作可继续流程"""
        nodes = ReactNodes(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=False,
            max_risk="high",
            auto_approve_safe=True,
            require_dry_run_for_high_risk=True,
        )

        state = {
            "current_instruction": {
                "worker": "system",
                "action": "delete_files",
                "args": {"files": ["tmp.txt"]},
                "risk_level": "high",
                "dry_run": True,
            },
            "is_simple_intent": False,
        }

        result = await nodes.safety_node(state)

        assert result.get("is_error") is None
        assert result.get("risk_level") == "high"
        assert result.get("needs_approval") is True

    @pytest.mark.asyncio
    async def test_medium_risk_no_approval_needed(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> None:
        """测试 medium 风险操作（如安装包、查看版本）不需要用户确认"""
        nodes = ReactNodes(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=False,
            max_risk="high",
            auto_approve_safe=True,
            require_dry_run_for_high_risk=False,
        )

        state = {
            "current_instruction": {
                "worker": "shell",
                "action": "execute_command",
                "args": {"command": "brew install nginx"},
                "risk_level": "medium",
                "dry_run": False,
            },
            "is_simple_intent": False,
        }

        result = await nodes.safety_node(state)

        assert result.get("is_error") is None
        assert result.get("needs_approval") is False

    @pytest.mark.asyncio
    async def test_safe_risk_no_approval_needed(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> None:
        """测试 safe 操作（如查看版本、列出文件）不需要用户确认"""
        nodes = ReactNodes(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=False,
            max_risk="high",
            auto_approve_safe=True,
            require_dry_run_for_high_risk=False,
        )

        state = {
            "current_instruction": {
                "worker": "shell",
                "action": "execute_command",
                "args": {"command": "node --version"},
                "risk_level": "safe",
                "dry_run": False,
            },
            "is_simple_intent": False,
        }

        result = await nodes.safety_node(state)

        assert result.get("is_error") is None
        assert result.get("needs_approval") is False


class TestCheckNodeErrorRecovery:
    """check_node 错误恢复测试"""

    @pytest.fixture
    def mock_llm(self) -> MockLLMClient:
        return MockLLMClient()

    @pytest.fixture
    def workers(self) -> dict[str, BaseWorker]:
        return {
            "system": SystemWorker(),
            "audit": AuditWorker(),
        }

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        return EnvironmentContext()

    @pytest.fixture
    def nodes(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> ReactNodes:
        return ReactNodes(
            llm_client=mock_llm,
            workers=workers,
            context=context,
            dry_run=False,
            max_risk="high",
            auto_approve_safe=True,
            require_dry_run_for_high_risk=False,
        )

    @pytest.mark.asyncio
    async def test_command_failure_triggers_recovery(self, nodes: ReactNodes) -> None:
        """命令执行失败（有 exit_code）应回到 reason 而非终止"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Command failed: brew services start nginx",
                "data": {
                    "command": "brew services start nginx",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "Bootstrap failed",
                },
                "task_completed": False,
            },
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 应该回到 reason（is_error=False, task_completed=False）
        assert result.get("is_error", False) is False
        assert result.get("task_completed") is False
        assert result.get("error_recovery_count") == 1
        assert result.get("iteration") == 1

    @pytest.mark.asyncio
    async def test_recovery_exhausted_becomes_fatal(self, nodes: ReactNodes) -> None:
        """恢复次数耗尽后应终止"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Command failed again",
                "data": {"command": "sudo nginx", "exit_code": 1, "stdout": "", "stderr": "error"},
                "task_completed": False,
            },
            "iteration": 2,
            "max_iterations": 5,
            "error_recovery_count": 2,  # 已经重试 2 次
        }

        result = await nodes.check_node(state)

        # 恢复次数耗尽，应该终止
        assert result.get("is_error") is True
        assert "Command failed again" in str(result.get("error_message", ""))

    @pytest.mark.asyncio
    async def test_system_error_is_immediately_fatal(self, nodes: ReactNodes) -> None:
        """系统级错误（无 exit_code，如 unknown worker）应立即终止"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Unknown worker: nonexistent",
                "data": None,
                "task_completed": False,
            },
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 系统错误不可恢复，应立即终止
        assert result.get("is_error") is True

    @pytest.mark.asyncio
    async def test_success_not_affected_by_recovery(self, nodes: ReactNodes) -> None:
        """成功执行不受恢复逻辑影响"""
        state = {
            "worker_result": {
                "success": True,
                "message": "Command succeeded",
                "data": {"command": "nginx", "exit_code": 0, "stdout": "ok"},
                "task_completed": False,
            },
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        assert result.get("is_error", False) is False
        assert result.get("task_completed") is False
        assert result.get("iteration") == 1

    @pytest.mark.asyncio
    async def test_max_iterations_stops_recovery(self, nodes: ReactNodes) -> None:
        """即使有恢复预算，达到 max_iterations 也应终止"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Command failed",
                "data": {"command": "nginx", "exit_code": 1, "stdout": "", "stderr": "err"},
                "task_completed": False,
            },
            "iteration": 4,  # next would be 5, hitting max
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # max_iterations 达到，不再恢复
        assert result.get("is_error") is True
