"""Prompt 模板管理"""

from __future__ import annotations

from typing import Optional

from src.context.environment import EnvironmentContext
from src.types import ConversationEntry
from src.workers.base import BaseWorker


class PromptBuilder:
    """Prompt 构建器

    管理 LLM 调用的 Prompt 模板
    """

    # Worker 能力描述
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
        "container": [
            "list_containers",
            "inspect_container",
            "logs",
            "restart",
            "stop",
            "start",
            "stats",
        ],
        "audit": ["log_operation"],
        "analyze": ["explain"],
        "http": ["fetch_url", "fetch_github_readme", "list_github_files"],
        "deploy": ["deploy"],  # 简化：只暴露一键部署
        "git": ["clone", "pull", "status"],  # Git 操作（显式路径优先）
    }

    def get_worker_capabilities(
        self, available_workers: Optional[dict[str, BaseWorker]] = None
    ) -> str:
        """获取 Worker 能力描述文本

        Returns:
            格式化的能力描述
        """
        lines = []
        if available_workers:
            for worker_name in sorted(available_workers.keys()):
                actions = available_workers[worker_name].get_capabilities()
                lines.append(f"- {worker_name}: {', '.join(actions)}")
        else:
            for worker, actions in self.WORKER_CAPABILITIES.items():
                lines.append(f"- {worker}: {', '.join(actions)}")
        return "\n".join(lines)

    def build_system_prompt(
        self,
        context: EnvironmentContext,
        available_workers: Optional[dict[str, BaseWorker]] = None,
    ) -> str:
        """构建系统提示

        Args:
            context: 环境上下文

        Returns:
            系统提示文本
        """
        env_context = context.to_prompt_context()
        worker_caps = self.get_worker_capabilities(available_workers)

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
  - ⚠️ OS-SPECIFIC COMMANDS (check Current Environment above!):
    * Kill process on port:
      - macOS/Darwin: lsof -ti :<PORT> | xargs kill -9
      - Linux: fuser -k <PORT>/tcp  OR  kill $(lsof -ti :<PORT>)
    * Find process on port:
      - macOS/Darwin: lsof -i :<PORT>
      - Linux: ss -tlnp | grep :<PORT>  OR  netstat -tlnp | grep :<PORT>
  - Examples:
    * List files: {{"worker": "shell", "action": "execute_command", "args": {{"command": "ls -la"}}, "risk_level": "safe"}}
    * Check disk: {{"worker": "shell", "action": "execute_command", "args": {{"command": "df -h"}}, "risk_level": "safe"}}
    * Docker containers (FULL TABLE): {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker ps"}}, "risk_level": "safe"}}
    * Docker details: {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker inspect container_name"}}, "risk_level": "safe"}}
    * Kill port 8000 (macOS): {{"worker": "shell", "action": "execute_command", "args": {{"command": "lsof -ti :8000 | xargs kill -9"}}, "risk_level": "high"}}

- chat.respond: Provide analysis and human-readable explanations
  - args: {{"message": "your detailed analysis"}}
  - Use this to explain technical output in natural language

- analyze.explain: ⭐ Intelligent analysis of ops objects (PREFERRED for "what is this?" questions)
  - args: {{"target": "<ACTUAL_NAME_FROM_CONTEXT>", "type": "docker|process|port|file|systemd"}}
  - CRITICAL: Extract the ACTUAL object name from conversation history or user input!
    * If user says "这个docker是干嘛的" after seeing "compoder-mongo" in output → target = "compoder-mongo"
    * If user says "8080端口是什么" → target = "8080"
    * NEVER use placeholder text like "object_name" or "docker_service_name_or_id"!
  - Automatically gathers info and provides Chinese summary
  - Use when user asks: "是干嘛的", "有什么用", "是什么", "解释", "分析", "explain", "what is"

- deploy.deploy: 一键部署 GitHub 项目（自动完成分析→克隆→配置→启动）
  - args: {{"repo_url": "https://github.com/owner/repo", "target_dir": "~/projects"}}
  - risk_level: medium
  - 示例: {{"worker": "deploy", "action": "deploy", "args": {{"repo_url": "https://github.com/user/app"}}, "risk_level": "medium"}}

- system/container: Avoid these - use shell commands instead

CRITICAL Rules:
1. ⭐⭐⭐ INTENT PRIORITY (意图优先级 - 最重要!!!):
   - If user mentions BOTH listing AND explaining, EXPLAINING takes priority!
   - "我只有一个docker服务，这个是干嘛的" → User already knows the list, wants EXPLANATION → use analyze.explain
   - "列出docker然后解释一下" → wants EXPLANATION → use analyze.explain (it will gather info automatically)
   - Key phrases for explanation intent: "是干嘛的", "有什么用", "是什么", "解释", "什么意思", "干什么的"
   - If user says "我只有一个X" or "就一个X", they already saw the list → go directly to analyze.explain!
2. For greetings, use chat.respond immediately
3. For listing/viewing info (docker services, files, processes):
   - ONLY when user ONLY asks to list (no explanation intent)
   - ALWAYS use FULL commands without --format flags
   - Show complete tables: "docker ps" NOT "docker ps --format"
4. ⭐⭐⭐ REFERENCE RESOLUTION (指代解析):
   - When user says "这个", "它", "这", "那个", "this", "that" → EXTRACT actual name from Previous actions Output!
   - Example: If docker ps output shows "compoder-mongo", and user says "这个是干嘛的" → target = "compoder-mongo" (NOT "这个"!)
   - Example: If output shows only ONE item, and user says "只有一个，这个是干嘛的" → use that ONE item's name
   - If user says "我只有一个docker服务" WITHOUT previous output → first run docker ps, then analyze
   - NEVER set target to pronouns like "这个", "它", "this" - always resolve to actual name!
5. For analysis questions (含"是干嘛的"、"有什么用"、"是什么"、"解释"、"分析"):
   - ⭐ PREFERRED: Use analyze.explain - it auto-gathers info and summarizes
   - MUST resolve references first (see rule 4)!
   - Example: {{"worker": "analyze", "action": "explain", "args": {{"target": "nginx", "type": "docker"}}, "risk_level": "safe"}}
4. Set risk_level: safe (read-only), medium (modifiable), high (destructive)
5. Output ONLY valid JSON, no markdown or extra text

Example workflows:
User: "我有哪些docker服务"
Step 1: {{"worker": "shell", "action": "execute_command", "args": {{"command": "docker ps"}}, "risk_level": "safe"}}

User: "这个 docker 是干嘛的" (referring to compoder-mongo from previous output)
Step 1: {{"worker": "analyze", "action": "explain", "args": {{"target": "compoder-mongo", "type": "docker"}}, "risk_level": "safe"}}

User: "8080 端口是什么服务"
Step 1: {{"worker": "analyze", "action": "explain", "args": {{"target": "8080", "type": "port"}}, "risk_level": "safe"}}

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}
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
            parts.append("Previous conversation:")
            for entry in history:
                # 显示用户的原始输入
                if entry.user_input:
                    parts.append(f"- User: {entry.user_input}")

                parts.append(f"  Action: {entry.instruction.worker}.{entry.instruction.action}")
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

    def build_deploy_prompt(
        self,
        context: EnvironmentContext,
        repo_url: str,
        target_dir: str = "~/projects",
        available_workers: Optional[dict[str, BaseWorker]] = None,
    ) -> str:
        """构建部署专用系统提示

        Args:
            context: 环境上下文
            repo_url: 仓库 URL
            target_dir: 部署目标目录

        Returns:
            部署系统提示文本
        """
        env_context = context.to_prompt_context()
        worker_caps = self.get_worker_capabilities(available_workers)

        return f"""You are an intelligent deployment assistant. Help the user deploy a GitHub project.

{env_context}

Available Workers:
{worker_caps}

## Deployment Workflow

1. First, use http.fetch_github_readme to get the project README
2. Use http.list_github_files to check for key files:
   - Dockerfile / docker-compose.yml → Prefer Docker deployment
   - package.json → Node.js project
   - requirements.txt / pyproject.toml → Python project
   - Makefile → Check for install/build targets

3. Based on analysis, choose deployment method:
   - Docker: git clone → docker compose up -d
   - Node.js: git clone → npm install → npm start
   - Python: git clone → pip install / uv sync → start command

4. Assess risk level based on command destructiveness:
   - safe: git clone, docker pull, read operations
   - medium: npm install, pip install, docker compose up
   - high: sudo, rm, overwrite existing files

## Worker Details

- http.fetch_github_readme: Get README content
  - args: {{"repo_url": "https://github.com/owner/repo"}}
  - Returns README content for analysis

- http.list_github_files: List repository file structure
  - args: {{"repo_url": "https://github.com/owner/repo", "path": ""}}
  - Detects key files: Dockerfile, package.json, requirements.txt, etc.

- shell.execute_command: Execute deployment commands
  - args: {{"command": "git clone ..."}}
  - Use for git clone, docker compose, npm install, etc.

## Target Repository
{repo_url}

## Target Directory
{target_dir}

## Instructions
1. Start by fetching README and listing files
2. Analyze project type and choose best deployment method
3. Execute deployment step by step
4. Report progress and handle errors

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}
"""
