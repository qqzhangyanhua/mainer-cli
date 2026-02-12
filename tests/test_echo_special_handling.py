"""测试 echo 命令的特殊处理"""

from src.orchestrator.command_whitelist import check_command_safety


class TestEchoSpecialHandling:
    """echo 命令特殊处理测试"""

    def test_echo_with_command_substitution_allowed(self) -> None:
        """测试 echo 中使用 $() 被允许"""
        command = "echo SECRET_KEY=$(openssl rand -hex 32) > .env"
        result = check_command_safety(command)

        assert result.allowed is True, f"echo with $() should be allowed, but got: {result.reason}"

    def test_echo_with_redirect_allowed(self) -> None:
        """测试 echo 中使用重定向被允许"""
        commands = [
            "echo VAR=value > .env",
            "echo VAR=value >> .env",
            "echo 'VAR=value' > .env",
        ]

        for command in commands:
            result = check_command_safety(command)
            assert result.allowed is True, f"{command} should be allowed, but got: {result.reason}"

    def test_echo_with_dangerous_patterns_still_blocked(self) -> None:
        """测试 echo 中的危险模式仍然被拦截"""
        dangerous_commands = [
            "echo test && rm -rf /",  # &&
            "echo test || rm -rf /",  # ||
            "echo test; rm -rf /",  # ;
            "echo test `rm -rf /`",  # `
            "echo test & rm -rf /",  # &
        ]

        for command in dangerous_commands:
            result = check_command_safety(command)
            assert result.allowed is False, f"{command} should be blocked"

    def test_non_echo_commands_still_strict(self) -> None:
        """测试非 echo 命令仍然严格检查"""
        dangerous_commands = [
            "cat file.txt > output.txt",  # > 在非 echo 中被拦截
            "docker run $(cat file.txt)",  # $() 在非 echo 中被拦截
        ]

        for command in dangerous_commands:
            result = check_command_safety(command)
            assert result.allowed is False, f"{command} should be blocked"

    def test_echo_complex_env_var_generation(self) -> None:
        """测试复杂的环境变量生成命令"""
        commands = [
            "echo SECRET_KEY=$(openssl rand -hex 32) > .env",
            "echo DATABASE_URL=postgresql://localhost/db >> .env",
            'echo "API_KEY=$(cat /tmp/key.txt)" >> .env',
        ]

        for command in commands:
            result = check_command_safety(command)
            assert result.allowed is True, f"{command} should be allowed"
