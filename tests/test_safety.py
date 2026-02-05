"""安全检查模块测试"""

from src.orchestrator.safety import DANGER_PATTERNS, check_safety
from src.types import Instruction


class TestSafetyCheck:
    """测试安全检查"""

    def test_safe_operations(self) -> None:
        """测试安全操作"""
        instruction = Instruction(
            worker="system",
            action="check_disk_usage",
            args={"path": "/"},
        )
        assert check_safety(instruction) == "safe"

    def test_high_risk_rm_rf(self) -> None:
        """测试高危 rm -rf"""
        instruction = Instruction(
            worker="system",
            action="delete_files",
            args={"command": "rm -rf /"},
        )
        assert check_safety(instruction) == "high"

    def test_high_risk_kill_9(self) -> None:
        """测试高危 kill -9"""
        instruction = Instruction(
            worker="system",
            action="execute",
            args={"command": "kill -9 1234"},
        )
        assert check_safety(instruction) == "high"

    def test_medium_risk_rm(self) -> None:
        """测试 rm 命令 - delete_files action 统一为高危"""
        instruction = Instruction(
            worker="system",
            action="delete_files",
            args={"command": "rm file.txt"},
        )
        # delete_files action 被设计为高危操作
        assert check_safety(instruction) == "high"

    def test_medium_risk_docker_rm(self) -> None:
        """测试中危 docker rm"""
        instruction = Instruction(
            worker="container",
            action="remove",
            args={"command": "docker rm container1"},
        )
        assert check_safety(instruction) == "medium"

    def test_danger_patterns_structure(self) -> None:
        """测试危险模式结构"""
        assert "high" in DANGER_PATTERNS
        assert "medium" in DANGER_PATTERNS
        assert "rm -rf" in DANGER_PATTERNS["high"]
        assert "rm " in DANGER_PATTERNS["medium"]
