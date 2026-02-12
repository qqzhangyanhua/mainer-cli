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
    async def test_high_risk_requires_dry_run_in_graph_mode(
        self,
        mock_llm: MockLLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
    ) -> None:
        """测试图模式高危操作必须先 dry-run"""
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

        assert result.get("is_error") is True
        assert "requires dry-run first" in str(result.get("error_message", ""))

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
