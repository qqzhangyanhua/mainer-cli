"""Shell 命令执行 Worker - 白名单化安全执行"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Tuple, Union, cast

from src.orchestrator.command_whitelist import CommandCheckResult, check_command_safety
from src.orchestrator.risk_analyzer import analyze_command_risk
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker

# 输出截断常量
MAX_OUTPUT_LENGTH = 4000
TRUNCATE_HEAD = 2000
TRUNCATE_TAIL = 2000

# 以 exit code 1 表示"无匹配/条件不满足"的命令（非错误）
# grep/egrep/fgrep: 无匹配行时返回 1
# diff: 文件有差异时返回 1
# test/[: 条件不成立时返回 1
_EXIT1_OK_COMMANDS = re.compile(r"^(grep|egrep|fgrep|diff|test|\[)$")


class ShellWorker(BaseWorker):
    """Shell 命令执行 Worker（白名单模式）

    支持的操作:
    - execute_command: 执行白名单内的 shell 命令

    安全机制:
    - 只允许执行预定义白名单内的命令
    - 禁止命令链接（&&, ||, ;）和危险重定向
    - 管道只允许接安全的文本处理命令
    - 某些命令禁止特定危险参数（如 rm -rf）
    """

    @property
    def name(self) -> str:
        return "shell"

    def get_capabilities(self) -> list[str]:
        return ["execute_command"]

    @staticmethod
    def _is_exit1_ok(command: str) -> bool:
        """判断命令是否属于 exit code 1 表示正常结果（无匹配）的类型

        对管道命令，检查最后一个管道段的主命令。
        例如 ``ps aux | grep nginx | grep -v grep`` 最后一段主命令为 ``grep``。
        """
        # 取管道最后一段
        last_segment = command.split("|")[-1].strip()
        # 提取主命令（跳过 env 变量赋值）
        parts = last_segment.split()
        cmd = ""
        for part in parts:
            if "=" in part and not part.startswith("-"):
                continue  # 跳过 VAR=value 形式
            cmd = part.split("/")[-1]  # 取 basename
            break
        return bool(_EXIT1_OK_COMMANDS.match(cmd))

    def _truncate_output(self, output: str) -> Tuple[str, bool]:
        """截断过长输出，保留头尾部分

        Args:
            output: 原始输出

        Returns:
            (截断后输出, 是否被截断)
        """
        if len(output) <= MAX_OUTPUT_LENGTH:
            return output, False

        truncated_chars = len(output) - TRUNCATE_HEAD - TRUNCATE_TAIL
        head = output[:TRUNCATE_HEAD]
        tail = output[-TRUNCATE_TAIL:]
        truncated_output = f"{head}\n\n... [truncated {truncated_chars} characters] ...\n\n{tail}"
        return truncated_output, True

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行 shell 操作"""
        if action != "execute_command":
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        command = args.get("command")
        if not isinstance(command, str):
            return WorkerResult(
                success=False,
                message="command must be a string",
            )

        working_dir = args.get("working_dir", os.getcwd())
        if not isinstance(working_dir, str):
            return WorkerResult(
                success=False,
                message="working_dir must be a string",
            )

        # 白名单安全检查 + 规则引擎兜底
        check_result = check_command_safety(command)
        if check_result.allowed is False:
            # 白名单明确拒绝（黑名单/危险模式/禁止标志）
            return WorkerResult(
                success=False,
                message=f"Command blocked: {check_result.reason}",
                data={"blocked": True, "command": command, "reason": check_result.reason},
            )
        elif check_result.allowed is None:
            # 白名单未匹配 → 规则引擎接管
            check_result = analyze_command_risk(command)
            if not check_result.allowed:
                return WorkerResult(
                    success=False,
                    message=f"Command blocked by risk analyzer: {check_result.reason}",
                    data={"blocked": True, "command": command, "reason": check_result.reason},
                )

        if dry_run:
            risk_info = f" [risk: {check_result.risk_level}]"
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would execute: {command} (cwd: {working_dir}){risk_info}",
                simulated=True,
                data={"risk_level": check_result.risk_level, "reason": check_result.reason},
            )

        # 执行命令（已通过白名单检查）
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,  # 禁用 stdin，避免等待用户输入
                cwd=working_dir,
            )

            stdout_bytes, stderr_bytes = await process.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            exit_code = process.returncode or 0

            # 判断是否成功：
            # - exit code 0 总是成功
            # - exit code 1 且命令属于 "exit1 正常" 类型（如 grep 无匹配）也视为成功
            if exit_code == 0:
                success = True
            elif exit_code == 1 and self._is_exit1_ok(command) and not stderr:
                success = True
            else:
                success = False

            # 截断过长输出用于 LLM 上下文传递
            raw_output, truncated = self._truncate_output(stdout)

            # 构建结果消息
            message_parts = [f"Command: {command}"]
            if exit_code == 1 and self._is_exit1_ok(command) and not stdout.strip():
                # 对 grep 等命令，无匹配时给出友好提示而非显示为错误
                message_parts.append("Output:\n(no matches found)")
            elif stdout:
                message_parts.append(f"Output:\n{stdout.strip()}")
            if stderr:
                message_parts.append(f"Stderr:\n{stderr.strip()}")
            message_parts.append(f"Exit code: {exit_code}")

            return WorkerResult(
                success=success,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {
                        "command": command,
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": exit_code,
                        "raw_output": raw_output,  # 用于 LLM 上下文传递
                        "truncated": truncated,  # 标记是否被截断
                    },
                ),
                message="\n".join(message_parts),
                # 不标记 task_completed，让 ReAct 循环继续回到 LLM，
                # 由 LLM 用 chat.respond 生成用户友好的自然语言回答
                task_completed=False,
            )

        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Failed to execute command: {e!s}",
            )
