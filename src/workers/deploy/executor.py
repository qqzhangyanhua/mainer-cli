"""Deploy Worker - 命令执行与 Docker 验证"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

from src.workers.deploy.diagnose import DeployDiagnoser
from src.workers.deploy.types import ConfirmationCallback, ProgressCallback
from src.workers.shell import ShellWorker


class DeployExecutor:
    """部署执行器：执行命令、重试、Docker 部署验证"""

    def __init__(
        self,
        shell: ShellWorker,
        diagnoser: DeployDiagnoser,
        progress_callback: ProgressCallback = None,
        confirmation_callback: ConfirmationCallback = None,
    ) -> None:
        self._shell = shell
        self._diagnoser = diagnoser
        self._progress_callback = progress_callback
        self._confirmation_callback = confirmation_callback

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback

    def set_confirmation_callback(self, callback: ConfirmationCallback) -> None:
        self._confirmation_callback = callback

    def _report_progress(self, step: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(step, message)

    async def execute_with_retry(
        self,
        step: dict[str, str],
        project_dir: str,
        project_type: str,
        known_files: list[str],
        max_retries: int = 3,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """执行命令，失败时使用 ReAct 循环自主诊断并重试

        Returns:
            (success, message)
        """
        command = step.get("command", "")
        description = step.get("description", command)

        if not command:
            return False, "空命令"

        if dry_run:
            return True, f"[DRY-RUN] 将执行: {command}"

        first_error: str = ""
        current_command = command

        for attempt in range(max_retries + 1):
            self._report_progress("deploy", f"    执行: {current_command[:80]}...")
            result = await self._shell.execute(
                "execute_command",
                {"command": current_command, "working_dir": project_dir},
            )

            if result.success:
                return True, f"✓ {description}"

            if attempt == 0:
                first_error = result.message

            if attempt == max_retries:
                return (
                    False,
                    f"✗ {description}\n命令: {current_command}\n错误: {first_error}",
                )

            self._report_progress("deploy", "    ⚠️ 命令失败，启动 AI 自主诊断...")
            fixed, diagnose_msg, fix_commands, new_command = (
                await self._diagnoser.react_diagnose_loop(
                    command=current_command,
                    error=result.message,
                    project_type=project_type,
                    project_dir=project_dir,
                    known_files=known_files,
                    confirmation_callback=self._confirmation_callback,
                    max_iterations=3,
                )
            )

            if not fixed:
                error_detail = (
                    f"✗ {description}\n命令: {current_command}\n错误: {first_error}"
                )
                if diagnose_msg:
                    error_detail += f"\n{diagnose_msg}"
                return False, error_detail

            if new_command:
                current_command = new_command
                self._report_progress("deploy", "    🔄 使用修改后的命令重试...")
            elif fix_commands:
                self._report_progress("deploy", "    ✓ 修复完成，重试原命令...")

        return (
            False,
            f"✗ {description}: 重试次数耗尽\n命令: {current_command}\n错误: {first_error}",
        )

    async def verify_docker_deployment(
        self,
        deploy_steps: list[dict[str, str]],
        project_dir: str,
        project_type: str,
        known_files: list[str],
        max_fix_attempts: int = 2,
    ) -> tuple[bool, str, Optional[dict[str, str]]]:
        """验证 Docker 部署是否成功"""
        container_name = None
        docker_run_command = None

        for step in deploy_steps:
            command = step.get("command", "")
            if "docker run" in command and "--name" in command:
                docker_run_command = command
                name_match = re.search(r"--name\s+(\S+)", command)
                if name_match:
                    container_name = name_match.group(1)
                    break

        if not container_name:
            self._report_progress("deploy", "    ℹ️ 未检测到 Docker 容器名称，跳过验证")
            return True, "未检测到容器名称", None

        self._report_progress("deploy", f"    🔍 检查容器 {container_name} 状态...")

        for attempt in range(max_fix_attempts + 1):
            check_result = await self._shell.execute(
                "execute_command",
                {
                    "command": (
                        f"docker ps --filter name=^{container_name}$ "
                        f"--format '{{{{.Names}}}} {{{{.Status}}}}'"
                    )
                },
            )

            if check_result.success and container_name in check_result.message:
                status_match = re.search(
                    rf"{container_name}\s+(.+)", check_result.message
                )
                status = status_match.group(1) if status_match else "running"

                if "Up" in status:
                    self._report_progress(
                        "deploy", f"    ✅ 容器 {container_name} 运行中: {status}"
                    )
                    return (
                        True,
                        f"✅ 容器验证通过: {container_name} ({status})",
                        {"container_name": container_name, "status": status},
                    )

            self._report_progress(
                "deploy", f"    ⚠️ 容器 {container_name} 未运行，检查原因..."
            )

            all_containers_result = await self._shell.execute(
                "execute_command",
                {
                    "command": (
                        f"docker ps -a --filter name=^{container_name}$ "
                        f"--format '{{{{.Names}}}} {{{{.Status}}}}'"
                    )
                },
            )

            container_exists = container_name in all_containers_result.message

            if container_exists:
                self._report_progress("deploy", "    📋 获取容器日志...")
                logs_result = await self._shell.execute(
                    "execute_command",
                    {"command": f"docker logs --tail 50 {container_name} 2>&1"},
                )
                container_logs = (
                    logs_result.message if logs_result.success else "无法获取日志"
                )
                error_message = (
                    f"容器 {container_name} 已退出。\n日志:\n{container_logs[:500]}"
                )
            else:
                error_message = f"容器 {container_name} 不存在"

            self._report_progress("deploy", f"    ❌ {error_message[:100]}...")

            if attempt < max_fix_attempts and docker_run_command:
                self._report_progress(
                    "deploy",
                    f"    🔧 尝试修复 (尝试 {attempt + 1}/{max_fix_attempts})...",
                )

                fixed, diagnose_msg, fix_commands, new_command = (
                    await self._diagnoser.react_diagnose_loop(
                        command=docker_run_command,
                        error=error_message,
                        project_type=project_type,
                        project_dir=project_dir,
                        known_files=known_files,
                        confirmation_callback=self._confirmation_callback,
                        max_iterations=2,
                    )
                )

                if fixed:
                    if new_command:
                        docker_run_command = new_command
                        self._report_progress("deploy", "    🔄 执行修复后的命令...")
                        run_result = await self._shell.execute(
                            "execute_command",
                            {"command": new_command, "working_dir": project_dir},
                        )
                        if not run_result.success:
                            self._report_progress(
                                "deploy",
                                f"    ❌ 修复命令执行失败: {run_result.message[:100]}",
                            )
                            continue

                    await asyncio.sleep(2)
                    continue
                else:
                    self._report_progress(
                        "deploy", f"    ❌ 无法自动修复: {diagnose_msg[:100]}"
                    )

            return (
                False,
                f"容器 {container_name} 启动失败: {error_message[:200]}",
                None,
            )

        return False, f"容器 {container_name} 验证失败", None

    async def read_file_safe(self, file_path: str, max_lines: int = 50) -> str:
        """安全读取文件内容"""
        try:
            if not os.path.exists(file_path):
                return "(文件不存在)"
            if not os.path.isfile(file_path):
                return "(不是文件)"
            if os.path.getsize(file_path) > 100000:
                return "(文件过大，跳过)"

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                content = "".join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (截断，共 {len(lines)} 行)"
                return content
        except Exception as e:
            return f"(读取失败: {e})"
