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
        """测试系统提示包含 macOS 内存查询命令示例"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 验证包含 macOS 内存查询的正确示例
        assert "Check memory usage:" in prompt
        # 验证 macOS 命令（不使用 --sort，因为 macOS 的 ps 不支持）
        assert "macOS/Darwin:" in prompt
        assert "sort -nrk 4" in prompt or "top -l 1 -o mem" in prompt or "vm_stat" in prompt
        # 验证 Linux 命令（使用 --sort）
        assert "Linux:" in prompt
        assert "--sort=-%mem" in prompt or "free -h" in prompt

    def test_system_prompt_contains_os_specific_examples(self) -> None:
        """测试系统提示包含操作系统特定的命令示例"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 验证包含操作系统特定命令的标记
        assert "OS-SPECIFIC COMMANDS" in prompt
        assert "check Current Environment" in prompt or "Current Environment" in prompt

    def test_system_prompt_contains_memory_query_workflow(self) -> None:
        """测试系统提示包含完整的内存查询工作流示例"""
        builder = PromptBuilder()
        context = EnvironmentContext()

        prompt = builder.build_system_prompt(context)

        # 验证包含内存查询的完整示例工作流
        assert "查看内存占用" in prompt or "内存占用情况" in prompt
        # 验证包含 macOS 和 Linux 两种命令
        assert "sort -nrk 4" in prompt  # macOS 命令
        assert "--sort=-%mem" in prompt  # Linux 命令
        # 验证强调了"先执行命令，再总结"的规则
        assert "execute the command FIRST" in prompt or "MUST execute" in prompt
        assert "NEVER skip command execution" in prompt
