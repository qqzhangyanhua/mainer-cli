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

    @staticmethod
    def _is_start_docker_desktop_command(command: str) -> bool:
        normalized = " ".join(command.lower().strip().split())
        return normalized in {
            "open -a docker",
            "open -a docker.app",
            'open -a "docker"',
            'open -a "docker.app"',
        }

    async def _wait_for_docker_ready(
        self, timeout_seconds: int = 90, interval_seconds: int = 3
    ) -> bool:
        """轮询 docker info，等待 Docker daemon 就绪"""
        elapsed = 0
        while elapsed <= timeout_seconds:
            check = await self._shell.execute(
                "execute_command",
                {"command": "docker info"},
            )
            if check.success:
                return True
            if elapsed >= timeout_seconds:
                break
            await asyncio.sleep(interval_seconds)
            elapsed += interval_seconds
        return False

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
        command = command.strip() if isinstance(command, str) else ""
        description = description.strip() if isinstance(description, str) else ""
        if not description:
            description = command or "未命名步骤"

        if not command:
            return True, "⏭️ 跳过空命令步骤"

        if dry_run:
            return True, f"[DRY-RUN] 将执行: {command}"

        first_error: str = ""
        current_command = command
        fix_notes: list[str] = []

        for attempt in range(max_retries + 1):
            self._report_progress("deploy", f"    执行: {current_command[:80]}...")
            result = await self._shell.execute(
                "execute_command",
                {"command": current_command, "working_dir": project_dir},
            )

            if result.success and self._is_start_docker_desktop_command(current_command):
                self._report_progress("deploy", "    ⏳ 等待 Docker daemon 就绪...")
                ready = await self._wait_for_docker_ready()
                if not ready:
                    return (
                        False,
                        "✗ Docker Desktop 启动后仍未就绪，请手动确认 Docker 已启动后重试",
                    )
            if result.success:
                msg = f"✓ {description}"
                if fix_notes:
                    msg += "\n" + "\n".join(f"    ⚠ {note}" for note in fix_notes)
                return True, msg

            if attempt == 0:
                first_error = result.message

            if attempt == max_retries:
                return (
                    False,
                    f"✗ {description}\n命令: {current_command}\n错误: {first_error}",
                )

            self._report_progress("deploy", "    ⚠️ 命令失败，启动 AI 自主诊断...")
            (
                fixed,
                diagnose_msg,
                fix_commands,
                new_command,
                cause,
            ) = await self._diagnoser.react_diagnose_loop(
                command=current_command,
                error=result.message,
                project_type=project_type,
                project_dir=project_dir,
                known_files=known_files,
                confirmation_callback=self._confirmation_callback,
                max_iterations=3,
            )

            if not fixed:
                error_detail = f"✗ {description}\n命令: {current_command}\n错误: {first_error}"
                if diagnose_msg:
                    error_detail += f"\n{diagnose_msg}"
                return False, error_detail

            if fixed and cause:
                fix_notes.append(cause)

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
        """验证 Docker 部署是否成功（支持 docker run 和 docker compose）"""
        container_name = None
        docker_run_command = None
        is_compose = False

        # 检测部署方式：docker compose 或 docker run
        for step in deploy_steps:
            command = step.get("command", "")
            if "docker compose up" in command or "docker-compose up" in command:
                is_compose = True
                docker_run_command = command
                break
            elif "docker run" in command and "--name" in command:
                docker_run_command = command
                name_match = re.search(r"--name\s+(\S+)", command)
                if name_match:
                    container_name = name_match.group(1)
                    break

        if not docker_run_command:
            self._report_progress("deploy", "    ℹ️ 未检测到 Docker 部署命令，跳过验证")
            return True, "未检测到 Docker 部署", None

        # docker compose 方式：获取项目名称和容器列表
        if is_compose:
            return await self._verify_compose_deployment(
                docker_run_command=docker_run_command,
                project_dir=project_dir,
                project_type=project_type,
                known_files=known_files,
                max_fix_attempts=max_fix_attempts,
            )

        # docker run 方式：验证单个容器
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
                status_match = re.search(rf"{container_name}\s+(.+)", check_result.message)
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

            self._report_progress("deploy", f"    ⚠️ 容器 {container_name} 未运行，检查原因...")

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
                container_logs = logs_result.message if logs_result.success else "无法获取日志"
                error_message = f"容器 {container_name} 已退出。\n日志:\n{container_logs[:500]}"
            else:
                error_message = f"容器 {container_name} 不存在"

            self._report_progress("deploy", f"    ❌ {error_message[:100]}...")

            if attempt < max_fix_attempts and docker_run_command:
                self._report_progress(
                    "deploy",
                    f"    🔧 尝试修复 (尝试 {attempt + 1}/{max_fix_attempts})...",
                )

                (
                    fixed,
                    diagnose_msg,
                    fix_commands,
                    new_command,
                    _cause,
                ) = await self._diagnoser.react_diagnose_loop(
                    command=docker_run_command,
                    error=error_message,
                    project_type=project_type,
                    project_dir=project_dir,
                    known_files=known_files,
                    confirmation_callback=self._confirmation_callback,
                    max_iterations=2,
                )

                if fixed and new_command:
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

                if fixed:
                    await asyncio.sleep(2)
                    continue

                self._report_progress("deploy", f"    ❌ 无法自动修复: {diagnose_msg[:100]}")

            return (
                False,
                f"容器 {container_name} 启动失败: {error_message[:200]}",
                None,
            )

        return False, f"容器 {container_name} 验证失败", None

    async def _verify_compose_deployment(
        self,
        docker_run_command: str,
        project_dir: str,
        project_type: str,
        known_files: list[str],
        max_fix_attempts: int = 2,
    ) -> tuple[bool, str, Optional[dict[str, str]]]:
        """验证 docker compose 部署"""
        self._report_progress("deploy", "    🔍 检查 docker compose 服务状态...")

        for attempt in range(max_fix_attempts + 1):
            # 获取所有运行中的容器
            check_result = await self._shell.execute(
                "execute_command",
                {
                    "command": "docker compose ps --format json",
                    "working_dir": project_dir,
                },
            )

            if (
                check_result.success
                and check_result.message.strip()
                and "running" in check_result.message.lower()
            ):
                # 简单检查：如果有输出且没有错误，认为服务在运行
                self._report_progress("deploy", "    ✅ docker compose 服务运行中")
                return (
                    True,
                    "✅ docker compose 服务验证通过",
                    {"deployment_type": "compose"},
                )

            # 服务未运行，获取详细日志
            self._report_progress("deploy", "    ⚠️ docker compose 服务未运行，检查原因...")
            logs_result = await self._shell.execute(
                "execute_command",
                {"command": "docker compose logs --tail 50", "working_dir": project_dir},
            )
            container_logs = logs_result.message if logs_result.success else "无法获取日志"
            error_message = f"docker compose 服务未运行。\n日志:\n{container_logs[:500]}"

            self._report_progress("deploy", f"    ❌ {error_message[:100]}...")

            if attempt < max_fix_attempts:
                self._report_progress(
                    "deploy",
                    f"    🔧 尝试修复 (尝试 {attempt + 1}/{max_fix_attempts})...",
                )

                (
                    fixed,
                    diagnose_msg,
                    fix_commands,
                    new_command,
                    _cause,
                ) = await self._diagnoser.react_diagnose_loop(
                    command=docker_run_command,
                    error=error_message,
                    project_type=project_type,
                    project_dir=project_dir,
                    known_files=known_files,
                    confirmation_callback=self._confirmation_callback,
                    max_iterations=2,
                )

                if fixed and new_command:
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

                if fixed:
                    await asyncio.sleep(2)
                    continue

                self._report_progress("deploy", f"    ❌ 无法自动修复: {diagnose_msg[:100]}")

        return False, f"docker compose 服务启动失败: {error_message[:200]}", None

    async def check_port_health(
        self,
        port: int,
        host: str = "localhost",
        timeout: int = 3,
    ) -> tuple[bool, str]:
        """检查端口健康状态

        Args:
            port: 端口号
            host: 主机地址
            timeout: 超时时间（秒）

        Returns:
            (is_healthy, message)
        """
        check_result = await self._shell.execute(
            "execute_command",
            {"command": f"curl -s -o /dev/null -w '%{{http_code}}' http://{host}:{port}"},
        )

        if check_result.success:
            # 检查 HTTP 状态码
            status_code = check_result.message.strip()
            if status_code.startswith("2") or status_code.startswith("3"):
                return True, f"端口 {port} 健康检查通过 (HTTP {status_code})"
            elif status_code == "000":
                # 000 表示无法连接，尝试使用 nc 检查
                pass
            else:
                # 4xx, 5xx 等也算是可以连接（说明服务在运行）
                return True, f"端口 {port} 可访问 (HTTP {status_code})"

        # curl 失败或返回 000，尝试使用 nc 检查端口
        nc_result = await self._shell.execute(
            "execute_command",
            {"command": f"nc -z -w {timeout} {host} {port}"},
        )

        if nc_result.success:
            return True, f"端口 {port} 可访问"

        return False, f"端口 {port} 无法连接"

    async def read_file_safe(self, file_path: str, max_lines: int = 50) -> str:
        """安全读取文件内容"""
        try:
            if not os.path.exists(file_path):
                return "(文件不存在)"
            if not os.path.isfile(file_path):
                return "(不是文件)"
            if os.path.getsize(file_path) > 100000:
                return "(文件过大，跳过)"

            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                content = "".join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (截断，共 {len(lines)} 行)"
                return content
        except Exception as e:
            return f"(读取失败: {e})"
