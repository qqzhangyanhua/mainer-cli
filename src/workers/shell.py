"""Shell 命令执行 Worker"""

from __future__ import annotations

import asyncio
import os
from typing import Union, cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


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
                cwd=working_dir,
            )

            stdout_bytes, stderr_bytes = await process.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            exit_code = process.returncode or 0
            success = exit_code == 0

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
                    dict[str, Union[str, int]],
                    {
                        "command": command,
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": exit_code,
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
