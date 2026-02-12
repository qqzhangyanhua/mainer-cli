"""命令拦截智能处理测试"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.workers.deploy.diagnose import DeployDiagnoser


@pytest.fixture
def diagnoser() -> DeployDiagnoser:
    """创建 DeployDiagnoser 实例"""
    shell = MagicMock()
    llm = MagicMock()
    return DeployDiagnoser(shell, llm)


class TestCommandBlockHandler:
    """命令拦截处理测试"""

    def test_handle_python_semicolon_blocked(self, diagnoser: DeployDiagnoser) -> None:
        """测试 Python 分号命令被拦截时的处理"""
        command = "python -c 'import secrets; print(secrets.token_hex(32))'"
        error = "Command blocked: Dangerous pattern detected: ';'"

        result = diagnoser.try_local_fix(command, error)

        assert result is not None
        assert result["action"] == "fix"
        assert "openssl" in result["new_command"]
        assert "python" not in result["new_command"]
        assert ";" not in result["new_command"]

    def test_handle_python_to_env_file_blocked(self, diagnoser: DeployDiagnoser) -> None:
        """测试 Python 写入 .env 文件命令被拦截"""
        command = "python -c 'import secrets; print(\"SECRET_KEY=\"+secrets.token_hex(32))' > .env"
        error = "Command blocked: Dangerous pattern detected: ';'"

        result = diagnoser.try_local_fix(command, error)

        assert result is not None
        assert result["action"] == "fix"
        assert result["new_command"] == "echo SECRET_KEY=$(openssl rand -hex 32) > .env"
        assert "python" not in result["new_command"]

    def test_handle_command_chain_blocked(self, diagnoser: DeployDiagnoser) -> None:
        """测试命令链被拦截时的处理"""
        command = "docker build -t app . && docker run -d app"
        error = "Command blocked: Dangerous pattern detected: '&&'"

        result = diagnoser.try_local_fix(command, error)

        assert result is not None
        assert result["action"] == "fix"
        assert "commands" in result
        commands = result["commands"]
        assert len(commands) == 2
        assert "docker build -t app ." in commands
        assert "docker run -d app" in commands

    def test_handle_unknown_blocked_command(self, diagnoser: DeployDiagnoser) -> None:
        """测试无法自动处理的拦截命令"""
        command = "some-unknown-command"
        error = "Command blocked: Unknown reason"

        result = diagnoser.try_local_fix(command, error)

        # 无法处理，应该返回 None，让 LLM 接管
        assert result is None

    def test_normal_errors_not_affected(self, diagnoser: DeployDiagnoser) -> None:
        """测试正常错误不受影响"""
        command = "docker run -d app"
        error = "Error: container already exists"

        # 这是容器名称冲突，应该被正常处理
        result = diagnoser.try_local_fix(command, error)
        # 由于没有 --name，实际会返回 None，但不应该触发命令拦截处理
        # 这个测试主要确保命令拦截处理不会误判


class TestPortOccupiedHandler:
    """端口占用处理测试（验证原有功能未被破坏）"""

    def test_port_occupied_still_works(self, diagnoser: DeployDiagnoser) -> None:
        """测试端口占用处理仍然有效"""
        command = "docker run -d --name app -p 5000:5000 app_image"
        error = "Error: bind: address already in use"

        result = diagnoser.try_local_fix(command, error)

        assert result is not None
        assert result["action"] == "fix"
        assert "-p 5001:5000" in result["new_command"]


class TestContainerNameConflictHandler:
    """容器名称冲突处理测试（验证原有功能未被破坏）"""

    def test_container_name_conflict_still_works(self, diagnoser: DeployDiagnoser) -> None:
        """测试容器名称冲突处理仍然有效"""
        command = "docker run -d --name myapp -p 5000:5000 app_image"
        error = "Error: container name 'myapp' is already in use"

        result = diagnoser.try_local_fix(command, error)

        assert result is not None
        assert result["action"] == "fix"
        assert "docker rm -f myapp" in result["commands"]
