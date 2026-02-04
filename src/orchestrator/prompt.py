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
        "analyze": ["explain"],
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
- shell.execute_command: Execute shell commands (⭐ PREFERRED for 95% of ops tasks)
  - ONLY action: "execute_command"
  - Required args: {{"command": "string"}}
  - Optional args: {{"working_dir": "string"}}
  - CRITICAL: Use FULL commands to show complete information
  - Examples:
    * List files: {{"worker": "shell", "action": "execute_command", "args": {{"command": "ls -la"}}, "risk_level": "safe"}}
    * Check disk: {{"worker": "shell", "action": "execute_command", "args": {{"command": "df -h"}}, "risk_level": "safe"}}
    * Docker containers (FULL TABLE): {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker ps"}}, "risk_level": "safe"}}
    * Docker details: {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker inspect container_name"}}, "risk_level": "safe"}}

- chat.respond: Provide analysis and human-readable explanations
  - args: {{"message": "your detailed analysis"}}
  - Use this to explain technical output in natural language

- analyze.explain: ⭐ Intelligent analysis of ops objects (PREFERRED for "what is this?" questions)
  - args: {{"target": "object_name", "type": "docker|process|port|file|systemd"}}
  - Automatically gathers info and provides Chinese summary
  - Use when user asks: "是干嘛的", "有什么用", "是什么", "解释", "分析", "explain", "what is"
  - Example: {{"worker": "analyze", "action": "explain", "args": {{"target": "compoder-mongo", "type": "docker"}}, "risk_level": "safe", "task_completed": true}}

- system/container: Avoid these - use shell commands instead

CRITICAL Rules:
1. For greetings, use chat.respond immediately
2. For listing/viewing info (docker services, files, processes):
   - ALWAYS use FULL commands without --format flags
   - Show complete tables: "docker ps" NOT "docker ps --format"
   - Show all columns (ID, image, ports, status, names, etc.)
   - ONLY use --format if user explicitly asks for specific fields
3. For analysis questions (含"是干嘛的"、"有什么用"、"是什么"、"解释"、"分析"):
   - ⭐ PREFERRED: Use analyze.explain - it auto-gathers info and summarizes
   - Set task_completed: true (analyze worker handles everything)
   - Example: {{"worker": "analyze", "action": "explain", "args": {{"target": "nginx", "type": "docker"}}, "risk_level": "safe", "task_completed": true}}
4. Set risk_level: safe (read-only), medium (modifiable), high (destructive)
5. Set task_completed: true when you provide the final answer
6. Output ONLY valid JSON, no markdown or extra text

Example workflows:
User: "我有哪些docker服务"
Step 1: {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker ps"}}, "risk_level": "safe", "task_completed": true}}

User: "这个 docker 是干嘛的" (referring to compoder-mongo from previous output)
Step 1: {{"worker": "analyze", "action": "explain", "args": {{"target": "compoder-mongo", "type": "docker"}}, "risk_level": "safe", "task_completed": true}}

User: "8080 端口是什么服务"
Step 1: {{"worker": "analyze", "action": "explain", "args": {{"target": "8080", "type": "port"}}, "risk_level": "safe", "task_completed": true}}

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high", "task_completed": true/false}}
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
                # 传递完整输出用于 LLM 分析（如果存在）
                if entry.result.data and isinstance(entry.result.data, dict):
                    raw_output = entry.result.data.get("raw_output")
                    if raw_output and isinstance(raw_output, str):
                        truncated = entry.result.data.get("truncated", False)
                        truncate_note = " [OUTPUT TRUNCATED]" if truncated else ""
                        parts.append(f"  Output{truncate_note}:")
                        parts.append(f"```\n{raw_output}\n```")
            parts.append("")

        parts.append(f"User request: {user_input}")

        return "\n".join(parts)
