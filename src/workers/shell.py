"""Shell 命令执行 Worker"""

from __future__ import annotations

import asyncio
import os
from typing import Tuple, Union, cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker

# 输出截断常量
MAX_OUTPUT_LENGTH = 4000
TRUNCATE_HEAD = 2000
TRUNCATE_TAIL = 2000


class ShellWorker(BaseWorker):
    """Shell 命令执行 Worker

    支持的操作:
    - execute_command: 执行 shell 命令
    """

    @property
    def name(self) -> str:
        return "shell"

    def get_capabilities(self) -> list[str]:
        return ["execute_command"]

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

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would execute: {command} (cwd: {working_dir})",
                simulated=True,
            )

        # 执行命令
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
            success = exit_code == 0

            # 截断过长输出用于 LLM 上下文传递
            raw_output, truncated = self._truncate_output(stdout)

            # 构建结果消息
            message_parts = [f"Command: {command}"]
            if stdout:
                message_parts.append(f"Output:\n{stdout.strip()}")
            if stderr:
                message_parts.append(f"Error:\n{stderr.strip()}")
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
                task_completed=success,
            )

        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Failed to execute command: {e!s}",
            )
