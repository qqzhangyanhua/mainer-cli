"""PolicyEngine 统一安全策略引擎测试"""

from src.orchestrator.policy_engine import PolicyEngine, PolicyResult
from src.types import Instruction


class TestPolicyEngineCheckInstruction:
    """check_instruction 测试"""

    def test_safe_shell_command(self) -> None:
        instruction = Instruction(
            worker="shell",
            action="execute_command",
            args={"command": "ls -la"},
            risk_level="safe",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.risk_level == "safe"
        assert result.allowed is True

    def test_dangerous_shell_command(self) -> None:
        instruction = Instruction(
            worker="shell",
            action="execute_command",
            args={"command": "rm -rf /"},
            risk_level="safe",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.allowed is False

    def test_medium_shell_command(self) -> None:
        instruction = Instruction(
            worker="shell",
            action="execute_command",
            args={"command": "docker stop mycontainer"},
            risk_level="safe",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.risk_level == "medium"
        assert result.allowed is True

    def test_non_shell_safe_worker(self) -> None:
        instruction = Instruction(
            worker="system",
            action="list_files",
            args={"path": "."},
            risk_level="safe",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.risk_level == "safe"
        assert result.allowed is True

    def test_non_shell_dangerous_action(self) -> None:
        instruction = Instruction(
            worker="system",
            action="delete_files",
            args={"files": ["test.txt"]},
            risk_level="high",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.risk_level == "high"

    def test_container_restart(self) -> None:
        instruction = Instruction(
            worker="container",
            action="restart",
            args={"container": "mycontainer"},
            risk_level="medium",
        )
        result = PolicyEngine.check_instruction(instruction)
        assert result.risk_level == "medium"


class TestPolicyEngineCheckCommand:
    """check_command 测试"""

    def test_whitelisted_safe_command(self) -> None:
        result = PolicyEngine.check_command("ls -la")
        assert result.allowed is True
        assert result.risk_level == "safe"

    def test_whitelisted_blocked_command(self) -> None:
        result = PolicyEngine.check_command("rm -rf /")
        assert result.allowed is False
        assert result.risk_level == "high"

    def test_unknown_command_goes_to_analyzer(self) -> None:
        result = PolicyEngine.check_command("my-custom-tool --check")
        # 规则引擎会分析并给出结果
        assert result.allowed is not None
        assert result.matched_by == "risk_analyzer"

    def test_blocked_command(self) -> None:
        result = PolicyEngine.check_command("sudo rm -rf /")
        assert result.allowed is False

    def test_echo_with_redirect_allowed(self) -> None:
        result = PolicyEngine.check_command("echo VAR=value > .env")
        assert result.allowed is True

    def test_echo_with_dangerous_chain_blocked(self) -> None:
        result = PolicyEngine.check_command("echo test && rm -rf /")
        assert result.allowed is False


class TestPolicyResult:
    """PolicyResult 数据类测试"""

    def test_creation(self) -> None:
        result = PolicyResult(risk_level="safe", allowed=True, reason="test")
        assert result.risk_level == "safe"
        assert result.allowed is True
        assert result.reason == "test"
