"""Prompt 模板管理"""

from __future__ import annotations

from typing import Optional

from src.context.environment import EnvironmentContext
from src.types import ConversationEntry


class PromptBuilder:
    """Prompt 构建器

    管理 LLM 调用的 Prompt 模板
    """

    # Worker 能力描述
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
        "container": ["list_containers", "restart_container", "view_logs"],
        "audit": ["log_operation"],
    }

    def get_worker_capabilities(self) -> str:
        """获取 Worker 能力描述文本

        Returns:
            格式化的能力描述
        """
        lines = []
        for worker, actions in self.WORKER_CAPABILITIES.items():
            lines.append(f"- {worker}: {', '.join(actions)}")
        return "\n".join(lines)

    def build_system_prompt(self, context: EnvironmentContext) -> str:
        """构建系统提示

        Args:
            context: 环境上下文

        Returns:
            系统提示文本
        """
        env_context = context.to_prompt_context()
        worker_caps = self.get_worker_capabilities()

        return f"""You are an ops automation assistant. Generate JSON instructions to solve user's task.

{env_context}

Available Workers:
{worker_caps}

Worker Details:
- shell.execute_command: Execute shell commands
  - ONLY action: "execute_command"
  - Required args: {{"command": "string"}}
  - Optional args: {{"working_dir": "string"}}
  - Examples:
    * List files: {{"worker": "shell", "action": "execute_command", "args": {{"command": "ls -la"}}, "risk_level": "safe"}}
    * Check disk: {{"worker": "shell", "action": "execute_command", "args": {{"command": "df -h"}}, "risk_level": "safe"}}

- system: Advanced file operations (find_large_files, check_disk_usage, delete_files)
- container: Docker management (list_containers, restart_container, view_logs)

IMPORTANT Rules:
1. For greetings (hello, hi, etc.), respond with: {{"worker": "chat", "action": "respond", "args": {{"message": "your greeting"}}, "risk_level": "safe", "task_completed": true}}
2. For ops tasks, PREFER shell.execute_command over system worker
3. ALL args values must be strings, integers, booleans, lists, or dicts - NO nested objects
4. Set risk_level: safe (read-only), medium (modifiable), high (destructive)
5. Output ONLY valid JSON, no extra text

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high", "task_completed": false}}
"""

    def build_user_prompt(
        self,
        user_input: str,
        history: Optional[list[ConversationEntry]] = None,
    ) -> str:
        """构建用户提示

        Args:
            user_input: 用户输入
            history: 对话历史

        Returns:
            用户提示文本
        """
        parts = []

        # 添加历史记录
        if history:
            parts.append("Previous actions:")
            for entry in history:
                parts.append(
                    f"- Action: {entry.instruction.worker}.{entry.instruction.action}"
                )
                parts.append(f"  Result: {entry.result.message}")
            parts.append("")

        parts.append(f"User request: {user_input}")

        return "\n".join(parts)
