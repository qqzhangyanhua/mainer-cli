"""Prompt 模板测试"""

from src.context.environment import EnvironmentContext
from src.orchestrator.prompt import PromptBuilder
from src.types import ConversationEntry, Instruction, WorkerResult


class TestPromptBuilder:
    """测试 Prompt 构建器"""

    def test_build_system_prompt(self) -> None:
        """测试构建系统提示"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        assert "ops automation assistant" in prompt.lower()
        assert "Available Workers:" in prompt
        assert "system:" in prompt
        assert "Output format:" in prompt
        assert context.os_type in prompt

    def test_build_user_prompt(self) -> None:
        """测试构建用户提示"""
        builder = PromptBuilder()

        prompt = builder.build_user_prompt("清理大文件")

        assert "清理大文件" in prompt
        assert "User request:" in prompt

    def test_build_user_prompt_with_history(self) -> None:
        """测试带历史的用户提示"""
        builder = PromptBuilder()

        history = [
            ConversationEntry(
                instruction=Instruction(
                    worker="system",
                    action="check_disk_usage",
                    args={},
                ),
                result=WorkerResult(
                    success=True,
                    data={"percent_used": 90},
                    message="Disk 90% used",
                ),
            )
        ]

        prompt = builder.build_user_prompt("继续清理", history=history)

        assert "继续清理" in prompt
        assert "Previous conversation:" in prompt
        assert "check_disk_usage" in prompt
        assert "Disk 90% used" in prompt

    def test_build_user_prompt_with_raw_output(self) -> None:
        """测试带完整输出的用户提示"""
        builder = PromptBuilder()

        history = [
            ConversationEntry(
                instruction=Instruction(
                    worker="shell",
                    action="execute_command",
                    args={"command": "docker ps"},
                ),
                result=WorkerResult(
                    success=True,
                    data={
                        "command": "docker ps",
                        "raw_output": "CONTAINER ID   IMAGE   STATUS\nabc123   nginx   Up 2 hours",
                        "truncated": False,
                    },
                    message="Command: docker ps",
                ),
            )
        ]

        prompt = builder.build_user_prompt("这是什么", history=history)

        assert "这是什么" in prompt
        assert "CONTAINER ID" in prompt
        assert "nginx" in prompt
        assert "Output:" in prompt
        assert "[OUTPUT TRUNCATED]" not in prompt

    def test_build_user_prompt_with_truncated_output(self) -> None:
        """测试带截断标记的用户提示"""
        builder = PromptBuilder()

        history = [
            ConversationEntry(
                instruction=Instruction(
                    worker="shell",
                    action="execute_command",
                    args={"command": "docker inspect test"},
                ),
                result=WorkerResult(
                    success=True,
                    data={
                        "command": "docker inspect test",
                        "raw_output": "{ long json content... }",
                        "truncated": True,
                    },
                    message="Command: docker inspect test",
                ),
            )
        ]

        prompt = builder.build_user_prompt("分析一下", history=history)

        assert "分析一下" in prompt
        assert "[OUTPUT TRUNCATED]" in prompt
        assert "long json content" in prompt

    def test_get_worker_capabilities(self) -> None:
        """测试获取 Worker 能力描述"""
        builder = PromptBuilder()

        caps = builder.get_worker_capabilities()

        assert "system:" in caps
        assert "find_large_files" in caps
        assert "check_disk_usage" in caps
