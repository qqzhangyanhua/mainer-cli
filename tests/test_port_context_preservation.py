"""测试端口号上下文保持功能

验证系统不会使用默认端口，而是从用户输入或上下文中提取实际端口号
"""

import pytest

from src.context.environment import EnvironmentContext
from src.orchestrator.prompt import PromptBuilder


class TestPortContextPreservation:
    """测试端口号上下文保持"""

    @pytest.fixture
    def prompt_builder(self) -> PromptBuilder:
        return PromptBuilder()

    @pytest.fixture
    def env_context(self) -> EnvironmentContext:
        return EnvironmentContext()

    def test_port_extraction_from_user_input(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试从用户输入中提取端口号"""
        test_cases = [
            ("nginx运行在8080端口", ["8080"]),
            ("重启8080端口的nginx", ["8080"]),
            ("关闭port 8080", ["8080"]),
            ("nginx在8080,redis在6380", ["8080", "6380"]),
            ("检查:8080的服务", ["8080"]),
        ]

        for user_input, expected_ports in test_cases:
            prompt = prompt_builder.build_user_prompt(user_input)

            # 验证端口号被提取并强调
            assert "PORT INFO FROM USER INPUT" in prompt, f"端口信息未被提取: {user_input}"

            for port in expected_ports:
                assert port in prompt, f"端口 {port} 未在 prompt 中: {user_input}"

    def test_default_port_warning_in_system_prompt(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试系统提示中包含端口发现相关指导"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        # 新 prompt 通过诊断流程引导先从配置发现端口，再检测监听
        assert "find_service_port" in system_prompt
        # 包含实际端口发现的命令示例
        assert "ss -tlnp" in system_prompt or "lsof -i" in system_prompt

    def test_port_specific_action_guidance(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试针对端口操作的特定指导"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        # 工具列表中包含 find_service_port
        assert "find_service_port" in system_prompt

        # 当有实际 worker 实例时，应包含详细描述
        from src.workers.monitor import MonitorWorker

        workers: dict[str, object] = {"monitor": MonitorWorker()}
        detailed_prompt = prompt_builder.build_system_prompt(
            env_context, available_workers=workers  # type: ignore[arg-type]
        )
        assert "monitor.find_service_port" in detailed_prompt

    def test_no_port_extraction_when_absent(self, prompt_builder: PromptBuilder) -> None:
        """测试当输入中没有端口号时，不应添加端口警告"""
        user_inputs_without_ports = [
            "列出所有docker容器",
            "查看内存使用情况",
            "重启nginx服务",  # 只有服务名，没有端口号
        ]

        for user_input in user_inputs_without_ports:
            prompt = prompt_builder.build_user_prompt(user_input)

            # 如果没有端口号，不应该有端口信息提示
            assert "PORT INFO FROM USER INPUT" not in prompt, f"错误提取了端口: {user_input}"

    def test_port_alternatives_when_unknown(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试系统提示中包含端口探测工具指导"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        # 验证 find_service_port 被包含在工具描述中
        assert "find_service_port" in system_prompt
        # 验证包含多种端口探测方法
        assert "ss -tlnp" in system_prompt or "lsof -i" in system_prompt
