"""Deploy Worker - 错误诊断与自动修复"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from typing import Optional

from src.llm.client import LLMClient
from src.workers.deploy.types import (
    DIAGNOSE_ERROR_PROMPT,
    ConfirmationCallback,
    ProgressCallback,
)
from src.workers.shell import ShellWorker


class DeployDiagnoser:
    """部署诊断器：错误分析、本地规则修复、LLM 诊断"""

    def __init__(
        self,
        shell: ShellWorker,
        llm: LLMClient,
        progress_callback: ProgressCallback = None,
        confirmation_callback: ConfirmationCallback = None,
        ask_user_callback: Optional[Callable[[str, list[str], str], Awaitable[str]]] = None,
    ) -> None:
        self._shell = shell
        self._llm = llm
        self._progress_callback = progress_callback
        self._confirmation_callback = confirmation_callback
        self._ask_user_callback = ask_user_callback

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback

    def set_confirmation_callback(self, callback: ConfirmationCallback) -> None:
        self._confirmation_callback = callback

    def set_ask_user_callback(
        self, callback: Optional[Callable[[str, list[str], str], Awaitable[str]]]
    ) -> None:
        self._ask_user_callback = callback

    def _report_progress(self, step: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(step, message)

    def try_local_fix(
        self,
        command: str,
        error: str,
    ) -> Optional[dict[str, object]]:
        """尝试本地规则修复（不依赖 LLM）"""
        error_lower = error.lower()

        # 命令被安全系统拦截：智能替代方案
        if "command blocked" in error_lower or "dangerous pattern" in error_lower:
            return self._handle_blocked_command(command, error)

        # 端口占用：直接换端口
        if "address already in use" in error_lower or (
            "port" in error_lower and "in use" in error_lower
        ):
            port_match = re.search(r"-p\s+(\d+):(\d+)", command)
            if port_match:
                host_port = int(port_match.group(1))
                container_port = port_match.group(2)
                new_host_port = host_port + 1
                new_command = re.sub(
                    r"-p\s+\d+:" + container_port,
                    f"-p {new_host_port}:{container_port}",
                    command,
                )
                return {
                    "action": "fix",
                    "thinking": [
                        f"观察：端口 {host_port} 被占用",
                        f"决策：改用端口 {new_host_port}",
                    ],
                    "new_command": new_command,
                    "cause": f"端口 {host_port} 被占用，已改用 {new_host_port}",
                }

        # 容器名称冲突：删除旧容器
        if "container name" in error_lower and "already in use" in error_lower:
            name_match = re.search(r"--name\s+(\S+)", command)
            if name_match:
                container_name = name_match.group(1)
                return {
                    "action": "fix",
                    "thinking": [
                        f"观察：容器 {container_name} 已存在",
                        "决策：先删除旧容器再创建",
                    ],
                    "commands": [f"docker rm -f {container_name}"],
                    "cause": f"容器 {container_name} 已存在，已删除旧容器",
                }

        return None

    def _handle_blocked_command(
        self,
        command: str,
        error: str,
    ) -> Optional[dict[str, object]]:
        """处理被拦截的命令 - 智能替代方案"""

        # 场景1：Python 生成密钥命令包含分号被拦截
        if (
            "python" in command
            and ("secrets" in command or "random" in command)
            and ("';'" in error or "dangerous pattern" in error.lower())
        ):
            self._report_progress(
                "deploy", "    🔄 检测到 Python 命令被拦截（包含分号），尝试 openssl 替代..."
            )
            # 替换为 openssl 命令
            # 检测是创建 .env 文件还是只生成密钥
            if "> .env" in command or ">> .env" in command:
                # 直接写入 .env
                return {
                    "action": "fix",
                    "thinking": [
                        "观察：Python 命令包含分号被安全系统拦截",
                        "分析：这是生成 SECRET_KEY 并写入 .env 的命令",
                        "决策：使用 openssl rand -hex 32 替代，避免分号",
                    ],
                    "new_command": "echo SECRET_KEY=$(openssl rand -hex 32) > .env",
                    "cause": "Python 命令被拦截，已改用 openssl 生成密钥",
                }
            else:
                # 只是生成密钥
                return {
                    "action": "fix",
                    "thinking": [
                        "观察：Python 命令包含分号被安全系统拦截",
                        "分析：这是生成随机密钥的命令",
                        "决策：使用 openssl rand -hex 32 替代",
                    ],
                    "new_command": "openssl rand -hex 32",
                    "cause": "Python 命令被拦截，已改用 openssl",
                }

        # 场景2：包含 && 或 || 的命令链被拦截
        if ("&&" in command or "||" in command) and (
            "'&&'" in error or "dangerous pattern" in error.lower()
        ):
            # 尝试分解为单独的命令
            self._report_progress("deploy", "    🔄 检测到命令链被拦截，尝试分解为独立命令...")

            # 简单分解（实际应该更智能）
            if "&&" in command:
                commands = [cmd.strip() for cmd in command.split("&&")]
            elif "||" in command:
                commands = [cmd.strip() for cmd in command.split("||")[:1]]  # 只取第一个
            else:
                commands = []

            if commands:
                return {
                    "action": "fix",
                    "thinking": [
                        "观察：命令链包含 && 或 || 被安全系统拦截",
                        "决策：分解为独立命令逐个执行",
                    ],
                    "commands": commands,
                    "cause": "命令链被拦截，已分解为独立命令",
                }

        # 场景3：包含重定向的命令被拦截（但实际上 > 和 >> 在某些情况下是允许的）
        # 这里不处理，让 LLM 处理更复杂的情况

        # 无法自动处理
        self._report_progress(
            "deploy", "    ⚠️ 命令被安全系统拦截，无法自动替代，将使用 LLM 诊断..."
        )
        return None

    async def llm_diagnose_error(
        self,
        command: str,
        error: str,
        project_type: str,
        project_dir: str,
        known_files: Optional[list[str]] = None,
        collected_info: Optional[str] = None,
    ) -> dict[str, object]:
        """LLM 诊断错误并提供修复方案"""
        # 1. 先尝试本地规则修复
        local_fix = self.try_local_fix(command, error)
        if local_fix:
            self._report_progress("deploy", "    🔧 使用本地规则修复...")
            return local_fix

        # 2. 本地无法修复，调用 LLM
        prompt = DIAGNOSE_ERROR_PROMPT.format(
            command=command,
            error=error[:1500],
            project_type=project_type,
            project_dir=project_dir,
            known_files=", ".join(known_files[:30]) if known_files else "(未知)",
            collected_info=collected_info or "(无)",
        )

        self._report_progress("deploy", "    🤖 调用 LLM 分析中...")

        try:
            response = await asyncio.wait_for(
                self._llm.generate(
                    "You are an ops expert. Diagnose and fix. Return only valid JSON.",
                    prompt,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            self._report_progress("deploy", "    ⚠️ LLM 响应超时")
            return {
                "action": "give_up",
                "cause": "LLM 响应超时",
                "suggestion": "请检查网络连接或稍后重试",
            }
        except Exception as e:
            self._report_progress("deploy", f"    ⚠️ LLM 调用失败: {e}")
            return {
                "action": "give_up",
                "cause": f"LLM 调用失败: {e}",
                "suggestion": "请检查 LLM 配置",
            }

        parsed = self._llm.parse_json_response(response)
        if not parsed:
            self._report_progress("deploy", "    ⚠️ LLM 返回格式错误")
            self._report_progress("deploy", f"    📝 LLM 原始响应: {response[:200]}...")
            return {
                "action": "give_up",
                "cause": "无法解析诊断结果",
                "suggestion": "请手动检查",
            }

        return parsed

    async def react_diagnose_loop(
        self,
        command: str,
        error: str,
        project_type: str,
        project_dir: str,
        known_files: list[str],
        confirmation_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        max_iterations: int = 3,
    ) -> tuple[bool, str, list[str], Optional[str], str]:
        """ReAct 循环自主诊断和修复

        Returns:
            (fixed, message, fix_commands, new_command, cause)
        """
        collected_info: list[str] = []
        fix_commands: list[str] = []

        for iteration in range(max_iterations):
            self._report_progress(
                "deploy", f"    🔍 AI 诊断中 (轮次 {iteration + 1}/{max_iterations})..."
            )

            diagnosis = await self.llm_diagnose_error(
                command=command,
                error=error,
                project_type=project_type,
                project_dir=project_dir,
                known_files=known_files,
                collected_info="\n".join(collected_info) if collected_info else None,
            )

            thinking = diagnosis.get("thinking", [])
            if isinstance(thinking, list):
                for thought in thinking:
                    self._report_progress("deploy", f"    💭 {thought}")

            action = diagnosis.get("action", "give_up")
            cause = diagnosis.get("cause", "")
            new_command = diagnosis.get("new_command")

            if cause:
                self._report_progress("deploy", f"    💡 分析: {cause}")

            if action == "give_up":
                suggestion = diagnosis.get("suggestion", "请手动检查项目")
                return False, f"原因: {cause}\n建议: {suggestion}", [], None, str(cause)

            elif action == "fix":
                if isinstance(new_command, str) and new_command:
                    self._report_progress("deploy", "    🔄 使用修改后的命令:")
                    self._report_progress("deploy", f"    📝 {new_command[:100]}...")
                    return True, "已生成修复命令", [], new_command, str(cause)

                commands = diagnosis.get("commands", [])
                if isinstance(commands, list):
                    for cmd in commands[:5]:
                        if isinstance(cmd, str) and cmd:
                            if self.is_destructive_command(cmd):
                                if confirmation_callback:
                                    self._report_progress("deploy", f"    ⚠️ 需要确认: {cmd}")
                                    confirmed = await confirmation_callback("执行命令", cmd)
                                    if not confirmed:
                                        collected_info.append(f"用户拒绝执行: {cmd}")
                                        continue
                                else:
                                    collected_info.append(f"跳过破坏性命令（需用户确认）: {cmd}")
                                    continue

                            self._report_progress("deploy", f"    🔧 修复: {cmd}")
                            result = await self._shell.execute(
                                "execute_command",
                                {"command": cmd, "working_dir": project_dir},
                            )
                            if result.success:
                                self._report_progress("deploy", "    ✓ 成功")
                                fix_commands.append(cmd)
                            else:
                                self._report_progress(
                                    "deploy", f"    ✗ 失败: {result.message[:100]}"
                                )
                                collected_info.append(
                                    f"修复命令 `{cmd}` 失败: {result.message[:200]}"
                                )

                if fix_commands:
                    return True, "已执行修复命令", fix_commands, None, str(cause)

            elif action == "ask_user":
                ask_info = diagnosis.get("ask_user", {})
                if isinstance(ask_info, dict):
                    question = str(ask_info.get("question", "请做出选择"))
                    options = ask_info.get("options", [])
                    context = str(ask_info.get("context", ""))
                    if not isinstance(options, list) or not options:
                        options = ["确认", "取消"]
                    options = [str(opt) for opt in options]
                    self._report_progress("deploy", f"    ❓ {question}")
                    if context:
                        self._report_progress("deploy", f"    📋 {context}")
                    if self._ask_user_callback:
                        user_choice = await self._ask_user_callback(question, options, context)
                        self._report_progress("deploy", f"    ✓ 用户选择: {user_choice}")
                        collected_info.append(f"用户选择: {user_choice}")
                        if not user_choice:
                            return False, "用户取消操作", [], None, ""
                    else:
                        collected_info.append(f"需要用户选择但无回调: {question}")
                        self._report_progress("deploy", "    ⚠️ 无法询问用户，跳过此步骤")

            elif action == "edit_file":
                edit_info = diagnosis.get("edit_file", {})
                if isinstance(edit_info, dict):
                    file_path = edit_info.get("path", "")
                    content = edit_info.get("content", "")
                    reason = edit_info.get("reason", "")
                    if file_path and content:
                        full_path = os.path.join(project_dir, file_path)
                        if confirmation_callback:
                            self._report_progress("deploy", f"    ✏️ 需要编辑: {file_path}")
                            self._report_progress("deploy", f"    原因: {reason}")
                            confirmed = await confirmation_callback(
                                f"编辑文件 {file_path}",
                                f"原因: {reason}\n内容预览: {content[:200]}...",
                            )
                            if confirmed:
                                try:
                                    with open(full_path, "w", encoding="utf-8") as f:
                                        f.write(str(content))
                                    self._report_progress("deploy", "    ✓ 文件已更新")
                                    fix_commands.append(f"edit:{file_path}")
                                    return (
                                        True,
                                        f"已编辑文件 {file_path}",
                                        fix_commands,
                                        None,
                                        str(cause),
                                    )
                                except Exception as e:
                                    collected_info.append(f"编辑文件失败: {e}")
                            else:
                                collected_info.append(f"用户拒绝编辑文件: {file_path}")
                        else:
                            collected_info.append(f"需要编辑文件但无法确认: {file_path}")
            else:
                collected_info.append(f"跳过操作: {action}")
                self._report_progress("deploy", "    ⚠️ 跳过探索操作，继续分析...")

        return False, "诊断超过最大尝试次数", [], None, ""

    @staticmethod
    def is_safe_read_command(cmd: str) -> bool:
        """检查是否是安全的只读命令"""
        safe_prefixes = [
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "pwd",
            "echo",
            "docker ps",
            "docker logs",
            "docker inspect",
            "docker images",
            "ps ",
            "ps aux",
            "env",
            "printenv",
            "which",
            "whereis",
            "file ",
            "stat ",
            "du ",
            "df ",
            "free",
            "uname",
            "python --version",
            "node --version",
            "docker --version",
        ]
        cmd_lower = cmd.lower().strip()
        return any(cmd_lower.startswith(prefix) for prefix in safe_prefixes)

    @staticmethod
    def is_destructive_command(cmd: str) -> bool:
        """检查是否是破坏性命令（需要用户确认）"""
        destructive_patterns = [
            "rm ",
            "rm -",
            "rmdir",
            "delete",
            "kill ",
            "kill -",
            "pkill",
            "killall",
            "sudo ",
            "chmod ",
            "chown ",
            "docker rm",
            "docker rmi",
            "docker stop",
            "docker kill",
            "> ",
            ">> ",
            "mv ",
            "cp -f",
        ]
        cmd_lower = cmd.lower().strip()
        return any(pattern in cmd_lower for pattern in destructive_patterns)
