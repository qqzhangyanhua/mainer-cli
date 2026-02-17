"""Prompt 模板管理"""

# ruff: noqa: E501  # Prompt templates contain long lines for readability

from __future__ import annotations

from typing import Optional

from src.context.environment import EnvironmentContext
from src.types import ConversationEntry, get_raw_output, is_output_truncated
from src.workers.base import BaseWorker


class PromptBuilder:
    """Prompt 构建器

    管理 LLM 调用的 Prompt 模板
    """

    # Worker 能力描述
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": [
            "list_files",
            "find_large_files",
            "check_disk_usage",
            "delete_files",
            "write_file",
            "append_to_file",
            "replace_in_file",
        ],
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
        "monitor": ["snapshot", "check_port", "check_http", "check_process", "top_processes", "find_service_port"],
        "log_analyzer": ["analyze_lines", "analyze_file", "analyze_container"],
        "remote": ["execute", "list_hosts", "test_connection"],
        "compose": ["status", "health", "logs", "restart", "up", "down"],
        "kubernetes": ["get", "describe", "logs", "top", "rollout", "scale"],
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

        return f"""You are an expert ops engineer agent. You diagnose problems thoroughly, execute commands to gather real evidence, and provide actionable conclusions.

{env_context}

## How you work (ReAct loop)
You operate in a loop. Each turn you:
1. THINK: Analyze all evidence gathered so far. What do you know? What's still unknown? What's the next most useful check?
2. ACT: Execute exactly one action to gather more evidence or fix the problem
3. The system shows you the result, then you think again

You keep looping until you have enough evidence to give a comprehensive answer, then give a final response via chat.respond.

## CRITICAL: When to finish
- Do NOT finish after a single check. One data point is not a diagnosis.
- You MUST use chat.respond with is_final=true to deliver your final answer to the user.
- Before finishing, ask yourself: "Have I answered the user's actual question with sufficient evidence?"
- A port check, process check, or log check alone is just one signal — keep investigating until you can explain the full picture.

## Diagnostic workflows

### Service health check ("检查/排查 XXX 服务")
When user asks to check, inspect, or troubleshoot a service, follow this diagnostic sequence:
1. **Process check**: Is the service process running? (monitor.check_process or shell: pgrep/ps)
2. **Port discovery**: What port is it actually listening on? (monitor.find_service_port) — NEVER assume default ports
3. **Port connectivity**: Is the port reachable? (monitor.check_port with the ACTUAL discovered port)
4. **HTTP check** (if applicable): Is the service responding to HTTP? (monitor.check_http)
5. **Log analysis**: Any errors in logs? (log_analyzer or shell: tail /var/log/xxx)
6. **Config check** (if issues found): Is the config valid? (shell: nginx -t, systemctl status, etc.)
7. **Summary**: Deliver a comprehensive diagnosis via chat.respond with is_final=true

You may skip steps that are clearly unnecessary, but NEVER stop after just 1-2 checks.

### Container troubleshooting ("检查/排查容器")
1. List containers (container.list_containers or shell: docker ps -a)
2. Inspect the target container (container.inspect_container)
3. Check container logs (container.logs or log_analyzer.analyze_container)
4. Check resource usage (container.stats)
5. Summary via chat.respond

### Performance investigation ("系统慢/负载高")
1. System snapshot (monitor.snapshot)
2. Top processes by CPU/memory (monitor.top_processes)
3. Disk I/O check (shell: iostat or iotop)
4. Network connections (shell: ss -s or netstat)
5. Summary via chat.respond

### Log analysis ("查看/分析日志")
1. Identify log location (shell: find or known paths)
2. Analyze logs (log_analyzer.analyze_file or log_analyzer.analyze_container)
3. If errors found, investigate root cause with additional commands
4. Summary via chat.respond

## Key principles
- ALWAYS execute commands to get real data. NEVER guess or respond with generic text.
- After destructive operations (kill, stop, rm, restart), ALWAYS verify with a follow-up command.
- When user challenges a result ("还能访问", "没生效", "不对"), ALWAYS re-verify with a command.
- NEVER assume default ports (nginx=80, redis=6379, etc.). Detect the actual port first.
- If monitor.find_service_port returns nothing, the service is likely not running — investigate why (check if installed, check systemd/docker, check logs).
- Resolve references ("这个", "它") to actual names/ports from previous output.
- Final responses to users MUST be in Chinese.
- Use OS-appropriate commands (check environment above for macOS vs Linux).

## Efficiency rules — avoid wasting iterations
- NEVER repeat the same action with the same arguments. If an action already returned a result, use that result.
- If monitor.find_service_port found nothing, do NOT call it again. Instead, try alternative approaches: shell commands like `lsof -i -P | grep <service>`, `ss -tlnp`, or check config files.
- Prefer shell.execute_command for flexible investigation when specialized tools don't give enough info.
- Each iteration is precious. Plan your diagnostic path to minimize steps.

## Shell command notes
- `&&` and `||` are allowed. The system checks each sub-command independently.
- `2>/dev/null` and `2>&1` are allowed (stderr handling). But `> file` is blocked — use system.write_file to write files.
- `|` (pipe) is allowed with text processing tools: grep, awk, sed, head, tail, sort, uniq, wc, cut, tr, tee, xargs, column, jq, less, cat.
- `;`, `$()`, backticks are NOT allowed.
- If a command is blocked, rewrite it to avoid the blocked pattern — do not retry the same command.

## Available tools
{worker_caps}

## Tool details
- shell.execute_command: Execute any shell command. args: {{"command": "string"}}. The system has an intelligent risk analyzer.
- chat.respond: Give a final natural language response. args: {{"message": "string"}}. MUST be used as the final step to deliver results to the user.
- analyze.explain: Intelligent analysis of ops objects. args: {{"target": "name", "type": "docker|process|port|file|systemd"}}
- monitor.find_service_port: Find actual listening port of a service. args: {{"name": "service_name"}}
- monitor.snapshot: System resource overview (CPU/memory/disk/load). args: {{}}
- monitor.check_port: TCP port check. args: {{"port": <PORT>}}
- monitor.check_http: HTTP health check. args: {{"url": "http://..."}}
- monitor.check_process: Check if a process is running. args: {{"name": "process_name"}}
- monitor.top_processes: Top processes by CPU or memory. args: {{"sort_by": "cpu|memory", "limit": 10}}
- deploy.deploy: One-click GitHub project deployment. args: {{"repo_url": "https://github.com/owner/repo"}}
- system.write_file: Create/overwrite file. args: {{"path": "filename", "content": "..."}}
- system.append_to_file: Append to file. args: {{"path": "filename", "content": "..."}}
- system.replace_in_file: Find and replace in file. args: {{"path": "filename", "old": "...", "new": "..."}}
- system.delete_files: Delete files. args: {{"files": ["path1", ...]}}
- log_analyzer.analyze_container/analyze_file: Analyze logs. args: {{"container": "name"}} or {{"path": "/var/log/..."}}
- remote.execute: SSH command on remote host. args: {{"host": "addr", "command": "cmd"}}
- compose.status/health/logs/restart/up/down: Docker Compose operations.
- kubernetes.get/describe/logs/top/rollout/scale: Kubernetes operations.

## Risk levels
- safe: read-only (ls, ps, df, docker ps, curl)
- medium: modifiable (install, write file, docker compose up)
- high: destructive (kill, rm, stop, docker compose down)

## Output format
Return a JSON object with three fields:
{{"thinking": "your reasoning about current state and next step", "action": {{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}, "is_final": false}}

When you have gathered enough evidence and want to give the final comprehensive response:
{{"thinking": "summarize all findings and reasoning about why the diagnosis is complete", "action": {{"worker": "chat", "action": "respond", "args": {{"message": "your comprehensive Chinese summary with findings and recommendations"}}, "risk_level": "safe"}}, "is_final": true}}

IMPORTANT: is_final should ONLY be true when using chat.respond to deliver the final answer. All intermediate investigation steps must have is_final: false.

Output ONLY valid JSON. No markdown, no extra text.
"""

    def build_user_prompt(
        self,
        user_input: str,
        history: Optional[list[ConversationEntry]] = None,
        thinking_history: Optional[list[str]] = None,
    ) -> str:
        """构建用户提示

        Args:
            user_input: 用户输入
            history: 对话历史
            thinking_history: LLM 推理历史

        Returns:
            用户提示文本
        """
        parts = []

        # 添加历史记录（包含 thinking）
        if history:
            parts.append("Previous actions and results:")
            for idx, entry in enumerate(history):
                if entry.user_input:
                    parts.append(f"- User: {entry.user_input}")

                # 如果有对应的 thinking 历史，展示 LLM 的推理过程
                if thinking_history and idx < len(thinking_history) and thinking_history[idx]:
                    parts.append(f"  Thinking: {thinking_history[idx]}")

                parts.append(f"  Action: {entry.instruction.worker}.{entry.instruction.action}")
                parts.append(f"  Result: {entry.result.message}")

                # 传递完整输出用于 LLM 分析（如果存在）
                raw_output = get_raw_output(entry.result)
                if raw_output:
                    truncated = is_output_truncated(entry.result)
                    truncate_note = " [OUTPUT TRUNCATED]" if truncated else ""
                    parts.append(f"  Output{truncate_note}:")
                    parts.append(f"```\n{raw_output}\n```")

            parts.append("")

        parts.append(f"User request: {user_input}")

        # 检测用户输入中的端口号并强调
        import re

        port_patterns = [
            r"(\d{1,5})\s*(?:端口|port)",
            r"(?:端口|port)\s*(\d{1,5})",
            r":\s*(\d{1,5})",
            r"(?:在|on)\s*(\d{1,5})",
        ]
        port_mentions = []
        for pattern in port_patterns:
            port_mentions.extend(re.findall(pattern, user_input, re.IGNORECASE))

        if port_mentions:
            unique_ports = sorted(set(port_mentions))
            parts.append("")
            parts.append(
                f"PORT INFO FROM USER INPUT: {', '.join(unique_ports)}"
            )
            parts.append("Use these EXACT port numbers, not default ports.")

        return "\n".join(parts)

    def build_deploy_prompt(
        self,
        context: EnvironmentContext,
        repo_url: str,
        target_dir: Optional[str] = None,
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
        if target_dir is None or not target_dir.strip():
            target_dir = context.cwd

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
