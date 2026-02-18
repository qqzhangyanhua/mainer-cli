"""P0-P3 重构的测试

覆盖：模型预设、Worker 自文档化、精简 Prompt、Function Calling schema、Runbook 系统
"""

from __future__ import annotations

import pytest

from src.context.environment import EnvironmentContext
from src.llm.presets import ModelPreset, get_preset, list_presets
from src.orchestrator.prompt import PromptBuilder
from src.runbooks.loader import RunbookLoader
from src.types import ActionParam, ToolAction
from src.workers.base import BaseWorker
from src.workers.chat import ChatWorker
from src.workers.shell import ShellWorker
from src.workers.system import SystemWorker


# ================================================================
# P0: 模型预设
# ================================================================


class TestModelPresets:
    """模型预设系统测试"""

    def test_list_presets_not_empty(self) -> None:
        presets = list_presets()
        assert len(presets) >= 5

    def test_get_known_preset(self) -> None:
        preset = get_preset("openai-gpt4o")
        assert preset is not None
        assert preset.model == "gpt-4o"
        assert preset.supports_function_calling is True
        assert preset.requires_api_key is True

    def test_get_local_preset(self) -> None:
        preset = get_preset("local-qwen")
        assert preset is not None
        assert preset.requires_api_key is False
        assert preset.supports_function_calling is False

    def test_get_unknown_preset(self) -> None:
        assert get_preset("nonexistent") is None

    def test_preset_fields(self) -> None:
        for preset in list_presets():
            assert preset.name
            assert preset.model
            assert preset.base_url
            assert preset.description
            assert preset.context_window > 0
            assert preset.recommended_max_tokens > 0


# ================================================================
# P1-a: Worker 自文档化
# ================================================================


class TestWorkerSelfDocumentation:
    """Worker 自文档化能力测试"""

    def test_shell_worker_has_description(self) -> None:
        worker = ShellWorker()
        assert worker.description
        assert "shell" in worker.description.lower() or "command" in worker.description.lower()

    def test_chat_worker_has_description(self) -> None:
        worker = ChatWorker()
        assert worker.description
        assert "final" in worker.description.lower() or "answer" in worker.description.lower()

    def test_system_worker_has_description(self) -> None:
        worker = SystemWorker()
        assert worker.description
        assert "file" in worker.description.lower()

    def test_shell_worker_get_actions(self) -> None:
        worker = ShellWorker()
        actions = worker.get_actions()
        assert len(actions) == 1
        assert actions[0].name == "execute_command"
        assert len(actions[0].params) >= 1
        assert actions[0].params[0].name == "command"

    def test_system_worker_get_actions(self) -> None:
        worker = SystemWorker()
        actions = worker.get_actions()
        action_names = [a.name for a in actions]
        assert "list_files" in action_names
        assert "check_disk_usage" in action_names
        assert "delete_files" in action_names

    def test_delete_files_is_high_risk(self) -> None:
        worker = SystemWorker()
        actions = worker.get_actions()
        delete_action = next(a for a in actions if a.name == "delete_files")
        assert delete_action.risk_level == "high"

    def test_get_tool_schema(self) -> None:
        worker = ShellWorker()
        schemas = worker.get_tool_schema()
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        func = schema["function"]
        assert isinstance(func, dict)
        assert func["name"] == "shell__execute_command"
        params = func["parameters"]
        assert isinstance(params, dict)
        assert "command" in params["properties"]

    def test_default_get_actions_fallback(self) -> None:
        """没有覆盖 get_actions 的 Worker 应该从 get_capabilities 生成"""
        from src.types import ArgValue, WorkerResult

        class MinimalWorker(BaseWorker):
            @property
            def name(self) -> str:
                return "minimal"

            def get_capabilities(self) -> list[str]:
                return ["do_thing"]

            async def execute(self, action: str, args: dict[str, ArgValue]) -> WorkerResult:
                return WorkerResult(success=True, message="ok")

        worker = MinimalWorker()
        actions = worker.get_actions()
        assert len(actions) == 1
        assert actions[0].name == "do_thing"
        assert actions[0].description == ""


# ================================================================
# P1-b: 精简 Prompt
# ================================================================


class TestSlimPrompt:
    """精简 Prompt 测试"""

    @pytest.fixture
    def env_context(self) -> EnvironmentContext:
        return EnvironmentContext()

    def test_prompt_is_shorter(self, env_context: EnvironmentContext) -> None:
        """新 prompt 应该比旧的短（旧的约 145 行 template）"""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(env_context)
        lines = prompt.strip().split("\n")
        assert len(lines) < 120

    def test_prompt_has_core_principles(self, env_context: EnvironmentContext) -> None:
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(env_context)
        assert "Evidence only" in prompt
        assert "Outside-in" in prompt or "outside-in" in prompt
        assert "Shell first" in prompt or "shell" in prompt.lower()

    def test_prompt_no_hardcoded_workflows(self, env_context: EnvironmentContext) -> None:
        """新 prompt 不应包含硬编码的诊断流程"""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(env_context)
        assert "### Service health check" not in prompt
        assert "### Container troubleshooting" not in prompt
        assert "### Performance investigation" not in prompt

    def test_prompt_has_output_format(self, env_context: EnvironmentContext) -> None:
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(env_context)
        assert "thinking" in prompt
        assert "is_final" in prompt
        assert "chat.respond" in prompt

    def test_dynamic_tool_descriptions(self, env_context: EnvironmentContext) -> None:
        """当传入 workers 时，应生成动态工具描述"""
        workers: dict[str, BaseWorker] = {
            "shell": ShellWorker(),
            "chat": ChatWorker(),
        }
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(
            env_context, available_workers=workers  # type: ignore[arg-type]
        )
        assert "shell.execute_command" in prompt
        assert "chat.respond" in prompt
        assert "whitelisted" in prompt.lower() or "command" in prompt.lower()

    def test_build_tool_descriptions_format(self) -> None:
        workers: dict[str, BaseWorker] = {
            "shell": ShellWorker(),
            "chat": ChatWorker(),
        }
        desc = PromptBuilder.build_tool_descriptions(workers)
        assert "### chat" in desc
        assert "### shell" in desc
        assert "shell.execute_command" in desc
        assert "chat.respond" in desc


# ================================================================
# P3: Runbook 系统
# ================================================================


class TestRunbookSystem:
    """Runbook 系统测试"""

    def test_loader_finds_runbooks(self) -> None:
        loader = RunbookLoader()
        runbooks = loader.list_all()
        assert len(runbooks) >= 5
        names = [rb.name for rb in runbooks]
        assert "service_health" in names
        assert "performance" in names

    def test_match_nginx_query(self) -> None:
        loader = RunbookLoader()
        matched = loader.match("检查下nginx的情况")
        assert len(matched) >= 1
        names = [rb.name for rb in matched]
        assert "service_health" in names

    def test_match_disk_query(self) -> None:
        loader = RunbookLoader()
        matched = loader.match("磁盘满了怎么办")
        assert len(matched) >= 1
        names = [rb.name for rb in matched]
        assert "disk_cleanup" in names

    def test_match_performance_query(self) -> None:
        loader = RunbookLoader()
        matched = loader.match("系统很慢，负载很高")
        assert len(matched) >= 1
        names = [rb.name for rb in matched]
        assert "performance" in names

    def test_match_docker_query(self) -> None:
        loader = RunbookLoader()
        matched = loader.match("docker容器挂了")
        assert len(matched) >= 1
        names = [rb.name for rb in matched]
        assert "container_troubleshoot" in names

    def test_match_no_result(self) -> None:
        loader = RunbookLoader()
        matched = loader.match("你好")
        assert len(matched) == 0

    def test_runbook_to_prompt_context(self) -> None:
        loader = RunbookLoader()
        rb = loader.get("service_health")
        assert rb is not None
        context = rb.to_prompt_context()
        assert "Diagnostic reference" in context
        assert "service_health" in context
        assert "Command:" in context

    def test_runbook_injected_into_prompt(self) -> None:
        """传入 user_input 时，匹配到的 Runbook 应注入到 prompt"""
        env_context = EnvironmentContext()
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(
            env_context, user_input="检查nginx状态"
        )
        assert "Diagnostic reference" in prompt
        assert "service_health" in prompt

    def test_no_runbook_for_generic_query(self) -> None:
        """无关请求不应注入 Runbook"""
        env_context = EnvironmentContext()
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(
            env_context, user_input="你好"
        )
        assert "Diagnostic reference" not in prompt

    def test_get_specific_runbook(self) -> None:
        loader = RunbookLoader()
        rb = loader.get("network_troubleshoot")
        assert rb is not None
        assert len(rb.steps) >= 3
        assert rb.keywords
