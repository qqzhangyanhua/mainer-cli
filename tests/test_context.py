"""环境上下文模块测试"""

import os
from unittest.mock import patch

from src.context.environment import EnvironmentContext


class TestEnvironmentContext:
    """测试环境上下文"""

    def test_collects_basic_info(self) -> None:
        """测试收集基本环境信息"""
        ctx = EnvironmentContext()

        assert ctx.os_type in ["Darwin", "Linux", "Windows"]
        assert ctx.os_version is not None
        assert ctx.cwd is not None
        assert ctx.user is not None
        assert ctx.timestamp is not None

    def test_shell_detection(self) -> None:
        """测试 Shell 检测"""
        ctx = EnvironmentContext()
        # Shell 应该是路径或 'unknown'
        assert ctx.shell == os.environ.get("SHELL", "unknown")

    def test_docker_availability_check(self) -> None:
        """测试 Docker 可用性检测"""
        ctx = EnvironmentContext()
        # docker_available 应该是布尔值
        assert isinstance(ctx.docker_available, bool)

    def test_to_prompt_context_format(self) -> None:
        """测试 Prompt 上下文格式"""
        ctx = EnvironmentContext()
        prompt_ctx = ctx.to_prompt_context()

        assert "Current Environment:" in prompt_ctx
        assert "OS:" in prompt_ctx
        assert "Shell:" in prompt_ctx
        assert "Working Directory:" in prompt_ctx
        assert "Docker:" in prompt_ctx
        assert "User:" in prompt_ctx

    @patch.dict(os.environ, {"SHELL": "/bin/zsh", "USER": "testuser"})
    def test_uses_environment_variables(self) -> None:
        """测试使用环境变量"""
        ctx = EnvironmentContext()
        assert ctx.shell == "/bin/zsh"
        assert ctx.user == "testuser"
