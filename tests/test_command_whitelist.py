"""Shell 命令白名单测试"""

import pytest

from src.orchestrator.command_whitelist import (
    check_command_safety,
    check_redirect_safety,
    parse_command,
    check_pipe_safety,
    check_dangerous_patterns,
    split_chain_commands,
)


class TestParseCommand:
    """命令解析测试"""

    def test_simple_command(self) -> None:
        base, sub, args = parse_command("ls -la")
        assert base == "ls"
        assert sub is None
        assert args == ["-la"]

    def test_docker_command(self) -> None:
        base, sub, args = parse_command("docker ps -a")
        assert base == "docker"
        assert sub == "ps"
        assert args == ["-a"]

    def test_git_command(self) -> None:
        base, sub, args = parse_command("git status --short")
        assert base == "git"
        assert sub == "status"
        assert args == ["--short"]

    def test_docker_compose_command(self) -> None:
        base, sub, args = parse_command("docker compose up -d")
        assert base == "docker-compose"
        assert sub == "up"
        assert args == ["-d"]

    def test_command_with_path(self) -> None:
        base, sub, args = parse_command("/usr/bin/ls -l")
        assert base == "ls"
        assert sub is None
        assert args == ["-l"]

    def test_empty_command(self) -> None:
        base, sub, args = parse_command("")
        assert base == ""
        assert sub is None
        assert args == []


class TestCheckDangerousPatterns:
    """危险模式检测测试"""

    def test_command_substitution(self) -> None:
        # echo 允许使用 $()，但非 echo 命令不允许
        result_echo = check_dangerous_patterns("echo $(whoami)")
        assert result_echo is None, "echo with $() should be allowed"

        result_other = check_dangerous_patterns("cat $(whoami)")
        assert result_other is not None, "non-echo commands should not allow $()"
        assert "$(" in result_other

    def test_backtick_substitution(self) -> None:
        # echo 中的 ` 由 _check_echo_safety 在 check_command_safety 流程中检查
        result = check_command_safety("echo `whoami`")
        assert result.allowed is False

    def test_command_chaining_not_in_dangerous_patterns(self) -> None:
        # && 和 || 不再由 check_dangerous_patterns 处理
        # 改由 split_chain_commands + check_command_safety 智能处理
        result = check_dangerous_patterns("ls && rm -rf /")
        assert result is None, "&& is now handled by split_chain_commands"

    def test_semicolon(self) -> None:
        result = check_dangerous_patterns("ls; rm -rf /")
        assert result is not None

    def test_redirection_not_in_dangerous_patterns(self) -> None:
        # > 不再由 check_dangerous_patterns 处理
        # 改由 check_redirect_safety 智能处理（允许 2>/dev/null 等）
        result = check_dangerous_patterns("cat file > output.txt")
        assert result is None, "> is now handled by check_redirect_safety"

        # echo 到系统目录仍被 _check_echo_safety 拦截
        result_dangerous = check_command_safety("echo 'pwned' > /etc/passwd")
        assert result_dangerous.allowed is False, "echo to system dir should be blocked"

    def test_safe_command(self) -> None:
        result = check_dangerous_patterns("ls -la")
        assert result is None

    def test_pipe_allowed(self) -> None:
        # 管道单独处理，不在这里拦截
        result = check_dangerous_patterns("ls | grep foo")
        assert result is None


class TestSplitChainCommands:
    """命令链拆分测试"""

    def test_no_chain(self) -> None:
        result = split_chain_commands("ls -la")
        assert result == ["ls -la"]

    def test_and_chain(self) -> None:
        result = split_chain_commands("ls && echo done")
        assert result == ["ls", "echo done"]

    def test_or_chain(self) -> None:
        result = split_chain_commands("nginx -t || echo failed")
        assert result == ["nginx -t", "echo failed"]

    def test_mixed_chain(self) -> None:
        result = split_chain_commands("cmd1 && cmd2 || cmd3")
        assert result == ["cmd1", "cmd2", "cmd3"]

    def test_respects_double_quotes(self) -> None:
        result = split_chain_commands('echo "hello && world" && ls')
        assert result == ['echo "hello && world"', "ls"]

    def test_respects_single_quotes(self) -> None:
        result = split_chain_commands("echo 'a || b' || exit 1")
        assert result == ["echo 'a || b'", "exit 1"]

    def test_pipe_not_split(self) -> None:
        result = split_chain_commands("ls | grep foo")
        assert result == ["ls | grep foo"]

    def test_pipe_with_chain(self) -> None:
        result = split_chain_commands("cat /etc/hosts | grep local && echo ok")
        assert result == ["cat /etc/hosts | grep local", "echo ok"]


class TestCheckRedirectSafety:
    """重定向安全检查测试"""

    def test_safe_stderr_devnull(self) -> None:
        assert check_redirect_safety("find / -name nginx.conf 2>/dev/null") is None

    def test_safe_stdout_devnull(self) -> None:
        assert check_redirect_safety("cmd >/dev/null") is None

    def test_safe_stderr_merge(self) -> None:
        assert check_redirect_safety("nginx -t 2>&1") is None

    def test_safe_combined(self) -> None:
        assert check_redirect_safety("cmd 2>&1 >/dev/null") is None

    def test_block_file_redirect(self) -> None:
        result = check_redirect_safety("cat file > output.txt")
        assert result is not None
        assert "redirect" in result.lower() or "file" in result.lower()

    def test_block_append_redirect(self) -> None:
        result = check_redirect_safety("echo test >> logfile")
        assert result is not None

    def test_block_input_redirect(self) -> None:
        result = check_redirect_safety("mysql < dump.sql")
        assert result is not None
        assert "input" in result.lower() or "<" in result

    def test_redirect_inside_quotes_ignored(self) -> None:
        assert check_redirect_safety('grep ">" file.txt') is None

    def test_safe_append_devnull(self) -> None:
        assert check_redirect_safety("cmd 2>>/dev/null") is None


class TestChainCommandSafety:
    """命令链安全检查集成测试"""

    def test_safe_chain_allowed(self) -> None:
        result = check_command_safety("ls -la && echo done")
        assert result.allowed is True

    def test_dangerous_chain_blocked(self) -> None:
        result = check_command_safety("ls && rm -rf /")
        assert result.allowed is False
        assert "chain" in result.reason.lower() or "blocked" in result.reason.lower()

    def test_or_chain_with_safe_commands(self) -> None:
        result = check_command_safety("nginx -t 2>/dev/null || echo 'nginx not found'")
        # nginx -t may or may not be in whitelist; but should not be blocked for &&/||
        assert result.allowed is not False or "chain" in (result.reason or "").lower()

    def test_chain_highest_risk(self) -> None:
        # Both commands allowed, but different risk levels
        result = check_command_safety("ls -la && df -h")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_redirect_with_chain(self) -> None:
        result = check_command_safety("nginx -t 2>/dev/null && echo ok")
        # Should not be blocked by redirect or chain patterns
        assert result.allowed is not False


class TestCheckPipeSafety:
    """管道安全检测测试"""

    def test_safe_pipe(self) -> None:
        result = check_pipe_safety("ls -la | grep foo | head -10")
        assert result is None

    def test_unsafe_pipe(self) -> None:
        result = check_pipe_safety("ls | rm -rf")
        assert result is not None
        assert "rm" in result

    def test_no_pipe(self) -> None:
        result = check_pipe_safety("ls -la")
        assert result is None

    def test_multiple_safe_pipes(self) -> None:
        result = check_pipe_safety("cat file | grep error | sort | uniq")
        assert result is None


class TestCheckCommandSafety:
    """命令安全检查测试"""

    # ========== 安全命令测试 ==========
    def test_ls_allowed(self) -> None:
        result = check_command_safety("ls -la")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_df_allowed(self) -> None:
        result = check_command_safety("df -h")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_test_command_allowed(self) -> None:
        result = check_command_safety("test -d /tmp")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_docker_ps_allowed(self) -> None:
        result = check_command_safety("docker ps -a")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_git_status_allowed(self) -> None:
        result = check_command_safety("git status")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_grep_allowed(self) -> None:
        result = check_command_safety("grep -r 'error' /var/log")
        assert result.allowed is True
        assert result.risk_level == "safe"

    # ========== 中风险命令测试 ==========
    def test_docker_restart_medium(self) -> None:
        result = check_command_safety("docker restart my-container")
        assert result.allowed is True
        assert result.risk_level == "medium"

    def test_git_pull_medium(self) -> None:
        result = check_command_safety("git pull origin main")
        assert result.allowed is True
        assert result.risk_level == "medium"

    def test_mkdir_medium(self) -> None:
        result = check_command_safety("mkdir -p /tmp/test")
        assert result.allowed is True
        assert result.risk_level == "medium"

    def test_touch_medium(self) -> None:
        result = check_command_safety("touch /tmp/test.txt")
        assert result.allowed is True
        assert result.risk_level == "medium"

    def test_open_docker_desktop_medium(self) -> None:
        result = check_command_safety("open -a Docker")
        assert result.allowed is True
        assert result.risk_level == "medium"

    def test_docker_compose_up_allowed(self) -> None:
        result = check_command_safety("docker compose up -d")
        assert result.allowed is True
        assert result.risk_level == "medium"

    # ========== 高风险命令测试 ==========
    def test_rm_high_risk(self) -> None:
        result = check_command_safety("rm file.txt")
        assert result.allowed is True
        assert result.risk_level == "high"

    def test_docker_rm_high_risk(self) -> None:
        result = check_command_safety("docker rm container-id")
        assert result.allowed is True
        assert result.risk_level == "high"

    def test_git_push_high_risk(self) -> None:
        result = check_command_safety("git push origin main")
        assert result.allowed is True
        assert result.risk_level == "high"

    def test_kill_high_risk(self) -> None:
        result = check_command_safety("kill 1234")
        assert result.allowed is True
        assert result.risk_level == "high"

    # ========== 被阻止的命令测试 ==========
    def test_rm_rf_blocked(self) -> None:
        result = check_command_safety("rm -rf /tmp/test")
        assert result.allowed is False
        assert "-rf" in result.reason or "-r" in result.reason

    def test_kill_9_blocked(self) -> None:
        result = check_command_safety("kill -9 1234")
        assert result.allowed is False
        assert "-9" in result.reason

    def test_chmod_777_blocked(self) -> None:
        result = check_command_safety("chmod 777 /tmp/test")
        assert result.allowed is False
        assert "777" in result.reason

    def test_find_delete_blocked(self) -> None:
        result = check_command_safety("find /tmp -name '*.log' -delete")
        assert result.allowed is False
        assert "-delete" in result.reason

    def test_sed_inplace_blocked(self) -> None:
        result = check_command_safety("sed -i 's/foo/bar/' file.txt")
        assert result.allowed is False
        assert "-i" in result.reason

    # ========== 绝对禁止的命令测试 ==========
    def test_sudo_blocked(self) -> None:
        result = check_command_safety("sudo ls")
        assert result.allowed is False
        assert "blocked" in result.reason.lower()

    def test_dd_blocked(self) -> None:
        result = check_command_safety("dd if=/dev/zero of=/dev/sda")
        assert result.allowed is False

    def test_mkfs_blocked(self) -> None:
        result = check_command_safety("mkfs.ext4 /dev/sda1")
        assert result.allowed is False

    def test_shutdown_blocked(self) -> None:
        result = check_command_safety("shutdown -h now")
        assert result.allowed is False

    def test_reboot_blocked(self) -> None:
        result = check_command_safety("reboot")
        assert result.allowed is False

    # ========== 不在白名单的命令测试 ==========
    def test_unknown_command_unmatched(self) -> None:
        """白名单未匹配的命令应返回 allowed=None（交由规则引擎）"""
        result = check_command_safety("my-custom-script.sh")
        assert result.allowed is None
        assert result.risk_level is None
        assert result.matched_by == "none"
        assert "not matched" in result.reason.lower()

    # ========== 危险模式测试 ==========
    def test_command_chaining_blocked(self) -> None:
        result = check_command_safety("ls && rm -rf /")
        assert result.allowed is False

    def test_command_substitution_blocked(self) -> None:
        # echo 允许安全的命令替换，但访问系统文件会被其他检查拦截
        # 测试非 echo 命令的 $() 被拦截
        result = check_command_safety("cat $(cat /etc/passwd)")
        assert result.allowed is False, "non-echo commands should block $()"

    def test_redirection_blocked(self) -> None:
        # echo 重定向到系统目录会被拦截
        result = check_command_safety("echo 'pwned' > /etc/passwd")
        assert result.allowed is False, "echo to /etc should be blocked"

    # ========== 管道测试 ==========
    def test_safe_pipe_allowed(self) -> None:
        result = check_command_safety("ls -la | grep test")
        assert result.allowed is True

    def test_unsafe_pipe_blocked(self) -> None:
        result = check_command_safety("ls | xargs rm -rf")
        # xargs 是允许的，但 rm 不在管道白名单
        # 实际上这个会被阻止因为 rm 不在 ALLOWED_PIPE_COMMANDS
        result = check_command_safety("cat file | sh")
        assert result.allowed is False

    def test_multiple_pipe_allowed(self) -> None:
        result = check_command_safety("ps aux | grep python | awk '{print $2}'")
        assert result.allowed is True

    # ========== 边界情况测试 ==========
    def test_empty_command(self) -> None:
        result = check_command_safety("")
        assert result.allowed is False

    def test_whitespace_command(self) -> None:
        result = check_command_safety("   ")
        assert result.allowed is False


class TestIntegrationWithSafety:
    """与 safety.py 集成测试"""

    def test_shell_instruction_safe(self) -> None:
        from src.orchestrator.safety import check_safety
        from src.types import Instruction

        instruction = Instruction(
            worker="shell",
            action="execute_command",
            args={"command": "ls -la"},
            risk_level="safe",
        )
        result = check_safety(instruction)
        assert result == "safe"

    def test_shell_instruction_blocked_returns_high(self) -> None:
        from src.orchestrator.safety import check_safety
        from src.types import Instruction

        instruction = Instruction(
            worker="shell",
            action="execute_command",
            args={"command": "sudo rm -rf /"},
            risk_level="safe",  # LLM 可能错误标记，但 safety 会覆盖
        )
        result = check_safety(instruction)
        assert result == "high"

    def test_non_shell_instruction_uses_pattern(self) -> None:
        from src.orchestrator.safety import check_safety
        from src.types import Instruction

        instruction = Instruction(
            worker="system",
            action="delete_files",
            args={"files": ["/tmp/test.txt"]},
            risk_level="safe",
        )
        result = check_safety(instruction)
        assert result == "high"  # delete_files 在 DANGER_PATTERNS 中
