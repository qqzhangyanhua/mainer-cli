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
        # 返回新格式：thinking + action + is_final
        return """```json
{
    "thinking": "This is a test greeting request",
    "action": {
        "worker": "chat",
        "action": "greet",
        "args": {},
        "risk_level": "safe"
    },
    "is_final": true
}
```"""

    def parse_json_response(self, response: str) -> dict[str, object] | None:
        """解析 JSON 响应（模拟）"""
        return {
            "thinking": "This is a test greeting request",
            "action": {
                "worker": "chat",
                "action": "greet",
                "args": {},
                "risk_level": "safe",
            },
            "is_final": True,
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


class TestPermissionErrorDetection:
    """权限错误检测与建议命令测试"""

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

    def test_detect_permission_denied_in_stderr(self) -> None:
        """stderr 含 'Permission denied' 应被检测"""
        data: dict[str, object] = {
            "stderr": "Error: Permission denied",
            "stdout": "",
        }
        assert ReactNodes._detect_permission_error(data) is True

    def test_detect_operation_not_permitted(self) -> None:
        """stderr 含 'Operation not permitted' 应被检测"""
        data: dict[str, object] = {
            "stderr": "nginx: Operation not permitted",
            "stdout": "",
        }
        assert ReactNodes._detect_permission_error(data) is True

    def test_no_false_positive(self) -> None:
        """'No such file or directory' 不应误判为权限错误"""
        data: dict[str, object] = {
            "stderr": "No such file or directory",
            "stdout": "",
        }
        assert ReactNodes._detect_permission_error(data) is False

    def test_build_sudo_command(self) -> None:
        """正确加 sudo 前缀，不重复"""
        assert ReactNodes._build_sudo_command("nginx -t") == "sudo nginx -t"
        assert ReactNodes._build_sudo_command("sudo nginx -t") == "sudo nginx -t"
        assert ReactNodes._build_sudo_command("  systemctl restart nginx") == "sudo systemctl restart nginx"

    @pytest.mark.asyncio
    async def test_check_node_permission_error_sets_suggested_commands(
        self, nodes: ReactNodes
    ) -> None:
        """权限错误 → task_completed=True + suggested_commands"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Command failed: systemctl restart nginx",
                "data": {
                    "command": "systemctl restart nginx",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "Failed to restart nginx.service: Permission denied",
                },
                "task_completed": False,
            },
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        assert result.get("task_completed") is True
        assert result.get("is_error") is False
        assert result.get("suggested_commands") == ["sudo systemctl restart nginx"]
        assert "权限不足" in str(result.get("final_message", ""))

    @pytest.mark.asyncio
    async def test_check_node_non_permission_error_still_recovers(
        self, nodes: ReactNodes
    ) -> None:
        """非权限错误仍走正常恢复循环"""
        state = {
            "worker_result": {
                "success": False,
                "message": "Command failed: nginx -t",
                "data": {
                    "command": "nginx -t",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "nginx: configuration file test failed",
                },
                "task_completed": False,
            },
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 非权限错误应走恢复逻辑
        assert result.get("is_error", False) is False
        assert result.get("task_completed") is False
        assert result.get("error_recovery_count") == 1
        assert result.get("suggested_commands") is None


class TestLLMIsFinalLogic:
    """llm_is_final 完成判断逻辑测试"""

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
    async def test_llm_is_final_true_completes_task(self, nodes: ReactNodes) -> None:
        """llm_is_final=True + worker 未完成时，LLM 可以加速结束"""
        state = {
            "worker_result": {
                "success": True,
                "message": "nginx 已停止，8080 端口已关闭",
                "data": {"command": "curl", "exit_code": 0, "stdout": "Connection refused"},
                "task_completed": False,  # worker 说没完成
            },
            "llm_is_final": True,  # 但 LLM 说完成了
            "iteration": 2,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # LLM is_final=True 加速完成
        assert result.get("task_completed") is True
        assert result.get("is_error", False) is False

    @pytest.mark.asyncio
    async def test_llm_is_final_false_cannot_override_worker_completed(self, nodes: ReactNodes) -> None:
        """llm_is_final=False 不能覆盖 worker 的 task_completed=True"""
        state = {
            "worker_result": {
                "success": True,
                "message": "你好！我是运维助手。",
                "data": None,
                "task_completed": True,  # chat.respond 标记完成
            },
            "llm_is_final": False,  # LLM 错误地设了 false
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # Worker 的 task_completed=True 优先，不被 LLM 覆盖
        assert result.get("task_completed") is True
        assert result.get("is_error", False) is False

    @pytest.mark.asyncio
    async def test_llm_is_final_false_continues_when_worker_not_completed(
        self, nodes: ReactNodes
    ) -> None:
        """llm_is_final=False + worker 未完成时继续循环"""
        state = {
            "worker_result": {
                "success": True,
                "message": "Command executed",
                "data": {"command": "ps aux", "exit_code": 0, "stdout": "nginx running"},
                "task_completed": False,  # shell 命令不标记完成
            },
            "llm_is_final": False,  # LLM 也说没完成
            "iteration": 1,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 继续循环
        assert result.get("task_completed") is False
        assert result.get("is_error", False) is False
        assert result.get("iteration") == 2

    @pytest.mark.asyncio
    async def test_no_llm_is_final_falls_back_to_worker(self, nodes: ReactNodes) -> None:
        """llm_is_final 未设置时回退到 worker 的 task_completed"""
        state = {
            "worker_result": {
                "success": True,
                "message": "分析完成",
                "data": None,
                "task_completed": True,
            },
            # llm_is_final 未设置
            "iteration": 0,
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 回退到 worker 的 task_completed=True
        assert result.get("task_completed") is True
        assert result.get("is_error", False) is False

    @pytest.mark.asyncio
    async def test_llm_is_final_false_force_summarize_near_max(self, nodes: ReactNodes) -> None:
        """倒数第二轮（max-1）设置 force_summarize=True"""
        state = {
            "worker_result": {
                "success": True,
                "message": "ok",
                "data": None,
                "task_completed": False,
            },
            "llm_is_final": False,
            "iteration": 3,  # next = 4, which is max_iterations - 1
            "max_iterations": 5,
            "error_recovery_count": 0,
        }

        result = await nodes.check_node(state)

        # 倒数第二轮：标记 force_summarize，继续循环
        assert result.get("task_completed") is False
        assert result.get("force_summarize") is True
        assert result.get("iteration") == 4

    @pytest.mark.asyncio
    async def test_llm_is_final_false_graceful_at_max_iterations(self, nodes: ReactNodes) -> None:
        """达到 max_iterations 时优雅降级，不报错"""
        state = {
            "worker_result": {
                "success": True,
                "message": "ok",
                "data": None,
                "task_completed": False,
            },
            "llm_is_final": False,
            "iteration": 4,  # next = 5, hitting max
            "max_iterations": 5,
            "error_recovery_count": 0,
            "user_input": "检查nginx服务",
            "messages": [],
        }

        result = await nodes.check_node(state)

        # 优雅降级：不报错，而是生成总结
        assert result.get("is_error", False) is False
        assert result.get("task_completed") is True
        assert result.get("final_message") is not None
        assert len(str(result.get("final_message", ""))) > 0
