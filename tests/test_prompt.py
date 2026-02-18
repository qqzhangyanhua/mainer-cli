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

        assert "senior ops engineer" in prompt.lower()
        assert "Available tools" in prompt
        assert "system:" in prompt
        assert "Output format" in prompt
        assert context.os_type in prompt
        # 新格式：包含 thinking + is_final
        assert "thinking" in prompt
        assert "is_final" in prompt

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
        assert "Previous actions and results:" in prompt
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

    def test_system_prompt_contains_macos_memory_commands(self) -> None:
        """测试系统提示包含 OS 环境信息"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 新 prompt 依赖 LLM 根据环境自行选择命令
        # 验证环境信息被包含
        assert context.os_type in prompt
        assert "OS:" in prompt

    def test_system_prompt_contains_os_specific_examples(self) -> None:
        """测试系统提示包含操作系统环境上下文"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 新 prompt 通过 Key principles 指导 LLM 使用 OS 适配命令
        assert "OS-appropriate commands" in prompt or "environment" in prompt.lower()

    def test_system_prompt_contains_memory_query_workflow(self) -> None:
        """测试系统提示包含 ReAct 循环工作流指导"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 新 prompt 的核心工作流：THINK → ACT → OBSERVE → REPEAT
        assert "THINK" in prompt
        assert "ACT" in prompt
        # 验证关键原则：真实数据驱动、不猜测
        assert "NEVER guess" in prompt
        assert "Commands first" in prompt or "shell.execute_command" in prompt
