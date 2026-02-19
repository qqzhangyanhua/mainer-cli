"""Prompt 模板管理 — 精简版，工具描述从 Worker 元数据动态生成"""

# ruff: noqa: E501  # Prompt templates contain long lines for readability

from __future__ import annotations

import re
from typing import Optional

from src.context.environment import EnvironmentContext
from src.runbooks.loader import RunbookLoader
from src.types import ConversationEntry, get_raw_output, is_output_truncated
from src.workers.base import BaseWorker


class PromptBuilder:
    """Prompt 构建器

    核心理念: 只告诉 LLM「做事原则」和「有什么工具可用」，
    不硬编码具体诊断流程，让模型自主推理。
    工具描述从 Worker 的 get_actions() 动态生成。
    """

    def __init__(self, runbook_loader: Optional[RunbookLoader] = None) -> None:
        self._runbook_loader = runbook_loader or RunbookLoader()

    # 静态 fallback（仅在没有 worker 实例时使用，如测试场景）
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": [
            "list_files", "find_large_files", "check_disk_usage", "delete_files",
            "write_file", "append_to_file", "replace_in_file",
        ],
        "container": [
            "list_containers", "inspect_container", "logs", "restart", "stop", "start", "stats",
        ],
        "audit": ["log_operation"],
        "analyze": ["explain"],
        "http": ["fetch_url", "fetch_github_readme", "list_github_files"],
        "deploy": ["deploy"],
        "git": ["clone", "pull", "status"],
        "monitor": [
            "snapshot", "check_port", "check_http", "check_process",
            "top_processes", "find_service_port",
        ],
        "log_analyzer": ["analyze_lines", "analyze_file", "analyze_container"],
        "remote": ["execute", "list_hosts", "test_connection"],
        "compose": ["status", "health", "logs", "restart", "up", "down"],
        "kubernetes": ["get", "describe", "logs", "top", "rollout", "scale"],
    }

    def get_worker_capabilities(
        self, available_workers: Optional[dict[str, BaseWorker]] = None
    ) -> str:
        """获取 Worker 能力描述文本（简略版，兼容旧接口）"""
        lines = []
        if available_workers:
            for worker_name in sorted(available_workers.keys()):
                actions = available_workers[worker_name].get_capabilities()
                lines.append(f"- {worker_name}: {', '.join(actions)}")
        else:
            for worker, actions in self.WORKER_CAPABILITIES.items():
                lines.append(f"- {worker}: {', '.join(actions)}")
        return "\n".join(lines)

    @staticmethod
    def build_tool_descriptions(workers: dict[str, BaseWorker]) -> str:
        """从 Worker 元数据动态生成工具描述

        这是 P1 重构的核心：工具描述不再硬编码在 prompt 里，
        而是由每个 Worker 的 description + get_actions() 自动生成。
        """
        sections: list[str] = []
        for worker_name in sorted(workers.keys()):
            worker = workers[worker_name]
            desc = worker.description
            actions = worker.get_actions()

            if not actions:
                continue

            header = f"### {worker_name}"
            if desc:
                header += f"\n{desc}"

            action_lines: list[str] = []
            for action in actions:
                params_str = ""
                if action.params:
                    param_parts = []
                    for p in action.params:
                        opt = "" if p.required else ", optional"
                        param_parts.append(f'{p.name}: {p.param_type}{opt} — {p.description}')
                    params_str = " | Params: " + "; ".join(param_parts)

                risk_tag = ""
                if action.risk_level != "safe":
                    risk_tag = f" [{action.risk_level}]"

                line = f"- **{worker_name}.{action.name}**{risk_tag}: {action.description}{params_str}"
                action_lines.append(line)

            sections.append(header + "\n" + "\n".join(action_lines))

        return "\n\n".join(sections)

    def build_system_prompt(
        self,
        context: EnvironmentContext,
        available_workers: Optional[dict[str, BaseWorker]] = None,
        user_input: Optional[str] = None,
    ) -> str:
        """构建系统提示

        精简版：只包含角色、原则、工具描述和输出格式。
        不包含硬编码的诊断流程 — 让 LLM 自主推理。
        当 user_input 提供时，会匹配相关 Runbook 并注入诊断参考。
        """
        env_context = context.to_prompt_context()

        if available_workers:
            tool_section = self.build_tool_descriptions(available_workers)
        else:
            tool_section = self.get_worker_capabilities()

        # 动态 Runbook 注入
        runbook_section = ""
        if user_input:
            matched = self._runbook_loader.match(user_input, top_k=2)
            if matched:
                parts = [rb.to_prompt_context() for rb in matched]
                runbook_section = (
                    "\n\n## Diagnostic reference (adapt to actual findings, do NOT follow blindly)\n"
                    + "\n\n".join(parts)
                )

        os_info = getattr(context, "os_info", "unknown")

        return f"""You are a senior ops engineer with deep Linux/container administration experience. You diagnose problems methodically: always gather evidence first, never guess. You communicate findings clearly in structured Chinese markdown.

{env_context}

## How you work (ReAct loop)
Each turn you THINK → ACT → OBSERVE, then repeat until you can deliver a comprehensive answer.
- THINK: What do I know? What's still unknown? What single action gives the most value?
- ACT: Execute exactly one action
- OBSERVE: Read the result, then think again
End by using chat.respond to deliver a clear, structured answer in Chinese.

## Core principles
1. **Evidence only**: Every claim must come from a command result. NEVER guess or assume.
2. **Outside-in diagnosis**: Start with basics (installed? version? config valid?) before runtime checks (ports? logs?).
3. **Adapt to OS**: This is {os_info}. Use OS-appropriate commands.
4. **Verify changes**: After any destructive op, run a follow-up command to confirm.
5. **Resolve references**: "这个"/"它"/"那个端口" — look up from conversation history.
6. **Chinese output**: Final answers MUST be in Chinese with markdown formatting.

## Tool selection priority
Use the most specific worker available. Fall back to shell only when no specialized worker covers the task.
1. **Specialized workers first**: container.list_containers over `docker ps`, monitor.snapshot over `free && df`, log_analyzer over `tail -f`.
2. **shell.execute_command**: Use for ad-hoc commands not covered by any worker, or when chaining multiple checks with `&&`/`|`.
3. **chat.respond**: ONLY for the final answer. Never use it for intermediate steps.

## Efficiency
- NEVER repeat the same command with the same arguments.
- Use `&&` to chain related checks: `which nginx && nginx -v`
- Use pipes to filter: `ps aux | grep nginx`, `ss -tlnp | grep :80`
- Use `2>/dev/null` to suppress expected errors.

## Shell rules
- `&&`, `||` allowed for chaining. `2>/dev/null`, `2>&1` allowed.
- `|` (pipe) allowed with: grep, awk, sed, head, tail, sort, uniq, wc, cut, tr, tee, xargs, column, jq.
- BLOCKED: `;`, `$()`, backticks, `> file` (use system.write_file instead).

## Available tools
{tool_section}

## Risk levels
- safe: read-only ops (ls, ps, cat, grep, curl, docker ps)
- medium: modifiable ops (install, write, restart)
- high: destructive ops (kill, rm, stop, docker rm)

## Output format
Return ONLY a valid JSON object:
{{"thinking": "brief reasoning", "action": {{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}, "is_final": false}}

For the final answer (MUST use chat.respond):
{{"thinking": "summarize findings", "action": {{"worker": "chat", "action": "respond", "args": {{"message": "中文 markdown 总结"}}, "risk_level": "safe"}}, "is_final": true}}

Rules:
- is_final MUST be true ONLY when using chat.respond.
- Output ONLY valid JSON. No markdown, no extra text.

## Examples

User: "nginx 为什么起不来"
{{"thinking": "先确认 nginx 是否安装及版本", "action": {{"worker": "shell", "action": "execute_command", "args": {{"command": "which nginx && nginx -v && nginx -t 2>&1"}}, "risk_level": "safe"}}, "is_final": false}}

User: "看看系统资源占用情况"
{{"thinking": "用 monitor.snapshot 获取 CPU/内存/磁盘全貌", "action": {{"worker": "monitor", "action": "snapshot", "args": {{}}, "risk_level": "safe"}}, "is_final": false}}

User: "查看容器日志"（history shows container name = my-app）
{{"thinking": "从历史得知目标容器是 my-app，用专用 worker 查日志", "action": {{"worker": "container", "action": "logs", "args": {{"container_id": "my-app", "tail": 100}}, "risk_level": "safe"}}, "is_final": false}}

After gathering enough evidence:
{{"thinking": "nginx 配置语法错误 /etc/nginx/nginx.conf:42 导致启动失败", "action": {{"worker": "chat", "action": "respond", "args": {{"message": "## 诊断结果\\n\\nnginx 启动失败，原因是配置文件语法错误..."}}, "risk_level": "safe"}}, "is_final": true}}
{runbook_section}"""

    def build_user_prompt(
        self,
        user_input: str,
        history: Optional[list[ConversationEntry]] = None,
        thinking_history: Optional[list[str]] = None,
    ) -> str:
        """构建用户提示"""
        parts: list[str] = []

        if history:
            parts.append("Previous actions and results:")
            for idx, entry in enumerate(history):
                if entry.user_input:
                    parts.append(f"- User: {entry.user_input}")

                if thinking_history and idx < len(thinking_history) and thinking_history[idx]:
                    parts.append(f"  Thinking: {thinking_history[idx]}")

                parts.append(f"  Action: {entry.instruction.worker}.{entry.instruction.action}")
                parts.append(f"  Result: {entry.result.message}")

                raw_output = get_raw_output(entry.result)
                if raw_output:
                    truncated = is_output_truncated(entry.result)
                    truncate_note = " [OUTPUT TRUNCATED]" if truncated else ""
                    parts.append(f"  Output{truncate_note}:")
                    parts.append(f"```\n{raw_output}\n```")

            parts.append("")

        parts.append(f"User request: {user_input}")

        port_patterns = [
            r"(\d{1,5})\s*(?:端口|port)",
            r"(?:端口|port)\s*(\d{1,5})",
            r":\s*(\d{1,5})",
            r"(?:在|on)\s*(\d{1,5})",
        ]
        port_mentions: list[str] = []
        for pattern in port_patterns:
            port_mentions.extend(re.findall(pattern, user_input, re.IGNORECASE))

        if port_mentions:
            unique_ports = sorted(set(port_mentions))
            parts.append("")
            parts.append(f"PORT INFO FROM USER INPUT: {', '.join(unique_ports)}")
            parts.append("Use these EXACT port numbers, not default ports.")

        return "\n".join(parts)

    def build_deploy_prompt(
        self,
        context: EnvironmentContext,
        repo_url: str,
        target_dir: Optional[str] = None,
        available_workers: Optional[dict[str, BaseWorker]] = None,
    ) -> str:
        """构建部署专用系统提示"""
        if target_dir is None or not target_dir.strip():
            target_dir = context.cwd

        env_context = context.to_prompt_context()
        worker_caps = self.get_worker_capabilities(available_workers)

        return f"""You are a deployment assistant. Deploy a GitHub project by examining its structure and choosing the best method.

{env_context}

Available Workers:
{worker_caps}

## Deployment principles
- Examine repo structure (README, Dockerfile, package.json, pyproject.toml) before executing anything.
- Prefer Docker when Dockerfile/docker-compose.yml exists.
- Assess risk level: read ops = safe, install/build = medium, sudo/rm/overwrite = high.
- Report each step's progress and handle errors with alternatives.

## Target
- Repository: {repo_url}
- Directory: {target_dir}

## Output format
{{"thinking": "...", "action": {{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}, "is_final": false}}

Final answer uses chat.respond with is_final: true.
"""
