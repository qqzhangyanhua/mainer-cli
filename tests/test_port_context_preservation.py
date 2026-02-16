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
            assert "CRITICAL PORT INFO EXTRACTED" in prompt, f"端口信息未被提取: {user_input}"

            for port in expected_ports:
                assert port in prompt, f"端口 {port} 未在 prompt 中: {user_input}"

    def test_default_port_warning_in_system_prompt(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试系统提示中包含默认端口警告"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        # 验证关键警告存在
        assert "NEVER USE DEFAULT PORTS" in system_prompt
        assert "nginx=80" in system_prompt
        assert "redis=6379" in system_prompt
        assert "postgres=5432" in system_prompt

        # 验证在 shell.execute_command 部分有警告
        shell_section = system_prompt.split("- shell.execute_command:")[1].split("- chat.respond:")[
            0
        ]
        assert "NEVER USE DEFAULT PORTS IN COMMANDS" in shell_section

    def test_port_specific_action_guidance(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试针对端口操作的特定指导"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        # 验证 REFERENCE RESOLUTION 规则中有端口相关指导
        assert "PORT-SPECIFIC ACTIONS" in system_prompt
        assert "lsof -ti :<PORT> | xargs kill -9" in system_prompt

        # 验证禁止使用默认端口的规则存在
        ref_section = system_prompt.split("REFERENCE RESOLUTION")[1].split("5. For analysis")[0]
        assert "NEVER USE DEFAULT PORTS" in ref_section
        assert "nginx on 8080" in ref_section  # 示例

    def test_no_port_extraction_when_absent(self, prompt_builder: PromptBuilder) -> None:
        """测试当输入中没有端口号时，不应添加端口警告"""
        user_inputs_without_ports = [
            "列出所有docker容器",
            "查看内存使用情况",
            "重启nginx服务",  # 只有服务名，没有端口号
        ]

        for user_input in user_inputs_without_ports:
            prompt = prompt_builder.build_user_prompt(user_input)

            # 如果没有端口号，不应该有 CRITICAL PORT INFO
            assert "CRITICAL PORT INFO EXTRACTED" not in prompt, f"错误提取了端口: {user_input}"

    def test_port_alternatives_when_unknown(
        self, prompt_builder: PromptBuilder, env_context: EnvironmentContext
    ) -> None:
        """测试当端口未知时的替代方案指导"""
        system_prompt = prompt_builder.build_system_prompt(env_context)

        ref_section = system_prompt.split("REFERENCE RESOLUTION")[1].split("5. For analysis")[0]

        # 验证提供了替代方案：优先使用 find_service_port 探测端口
        assert "find_service_port" in ref_section
        assert "Ask user" in ref_section or "请明确指定要操作的端口号" in ref_section
