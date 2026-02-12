"""容器操作 Worker - 基于 Shell 命令（无需 docker-py）"""

from __future__ import annotations

import json
import re
from typing import cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.shell import ShellWorker


class ContainerWorker(BaseWorker):
    """Docker 容器管理 Worker（基于 shell 命令）

    支持的操作:
    - list_containers: 列出容器
    - inspect_container: 查看容器详情
    - logs: 获取容器日志
    - restart: 重启容器
    - stop: 停止容器
    - start: 启动容器
    - stats: 获取资源统计

    优势：
    - 无需 docker-py 依赖（减少 50MB）
    - 更直观的错误提示
    - 与 Docker CLI 行为一致
    """

    def __init__(self) -> None:
        """初始化 Container Worker"""
        self._shell = ShellWorker()

    @property
    def name(self) -> str:
        return "container"

    def get_capabilities(self) -> list[str]:
        return [
            "list_containers",
            "inspect_container",
            "logs",
            "restart",
            "stop",
            "start",
            "stats",
        ]

    async def _check_docker_available(self) -> tuple[bool, str]:
        """检查 Docker 是否可用

        Returns:
            (是否可用, 错误消息)
        """
        result = await self._shell.execute(
            "execute_command",
            {"command": "docker --version"},
        )
        if not result.success:
            return False, "Docker not found. Please install Docker."

        # 检查 Docker daemon 是否运行
        result = await self._shell.execute(
            "execute_command",
            {"command": "docker ps"},
        )
        if not result.success:
            return False, "Cannot connect to Docker daemon. Is Docker running?"

        return True, ""

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行容器操作"""
        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        handlers = {
            "list_containers": self._list_containers,
            "inspect_container": self._inspect_container,
            "logs": self._logs,
            "restart": self._restart,
            "stop": self._stop,
            "start": self._start,
            "stats": self._stats,
        }

        handler = handlers.get(action)
        if handler is None:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        # dry_run 模式下跳过 Docker 检查
        if not dry_run:
            available, error = await self._check_docker_available()
            if not available:
                return WorkerResult(success=False, message=error)

        try:
            return await handler(args, dry_run=dry_run)
        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Error executing {action}: {e!s}",
            )

    async def _list_containers(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """列出容器"""
        all_containers = args.get("all", False)
        if isinstance(all_containers, str):
            all_containers = all_containers.lower() == "true"

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would list containers (all={all_containers})",
                simulated=True,
            )

        # 使用 docker ps 命令
        cmd = "docker ps --format '{{json .}}'"
        if all_containers:
            cmd += " -a"

        result = await self._shell.execute(
            "execute_command",
            {"command": cmd},
        )

        if not result.success:
            return WorkerResult(
                success=False,
                message=f"Failed to list containers: {result.message}",
            )

        # 解析 JSON 输出
        data: list[dict[str, str | int]] = []
        raw_output = result.data.get("raw_output", "") if result.data else ""
        if isinstance(raw_output, str):
            for line in raw_output.strip().split("\n"):
                if not line:
                    continue
                try:
                    container = json.loads(line)
                    data.append(
                        {
                            "id": container.get("ID", "")[:12],  # 短 ID
                            "name": container.get("Names", ""),
                            "status": container.get("Status", ""),
                            "image": container.get("Image", ""),
                        }
                    )
                except json.JSONDecodeError:
                    continue

        return WorkerResult(
            success=True,
            data=data,
            message=f"Found {len(data)} containers",
            task_completed=True,
        )

    async def _inspect_container(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """查看容器详情"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would inspect container: {container_id}",
                simulated=True,
            )

        # 使用 docker inspect 命令
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker inspect {container_id}"},
        )

        if not result.success:
            # 检查是否是容器未找到
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to inspect container: {result.message}",
            )

        # 解析 JSON 输出
        raw_output = result.data.get("raw_output", "") if result.data else ""
        if isinstance(raw_output, str):
            try:
                inspect_data = json.loads(raw_output)
                if isinstance(inspect_data, list) and len(inspect_data) > 0:
                    container = inspect_data[0]

                    state = container.get("State", {})
                    config = container.get("Config", {})

                    data: dict[str, str | int] = {
                        "id": container.get("Id", "")[:12],
                        "name": container.get("Name", "").lstrip("/"),
                        "status": state.get("Status", ""),
                        "image": config.get("Image", ""),
                        "created": container.get("Created", ""),
                        "restart_count": state.get("RestartCount", 0),
                    }

                    return WorkerResult(
                        success=True,
                        data=cast(dict[str, str | int], data),
                        message=f"Container {container_id} status: {state.get('Status', 'unknown')}",
                        task_completed=True,
                    )
            except json.JSONDecodeError:
                pass

        return WorkerResult(
            success=False,
            message="Failed to parse container inspection data",
        )

    async def _logs(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """获取容器日志"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        tail = args.get("tail", 100)
        if not isinstance(tail, int):
            tail = 100

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would fetch logs from {container_id} (tail={tail})",
                simulated=True,
            )

        # 使用 docker logs 命令
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker logs --tail {tail} --timestamps {container_id}"},
        )

        if not result.success:
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to get logs: {result.message}",
            )

        logs = result.data.get("raw_output", "") if result.data else ""

        return WorkerResult(
            success=True,
            data={"logs": logs},
            message=f"Retrieved {tail} lines from {container_id}",
            task_completed=True,
        )

    async def _restart(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """重启容器"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would restart container: {container_id}",
                simulated=True,
            )

        # 使用 docker restart 命令
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker restart {container_id}"},
        )

        if not result.success:
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to restart container: {result.message}",
            )

        return WorkerResult(
            success=True,
            message=f"Container {container_id} restarted successfully",
            task_completed=True,
        )

    async def _stop(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """停止容器"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would stop container: {container_id}",
                simulated=True,
            )

        # 使用 docker stop 命令
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker stop {container_id}"},
        )

        if not result.success:
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to stop container: {result.message}",
            )

        return WorkerResult(
            success=True,
            message=f"Container {container_id} stopped successfully",
            task_completed=True,
        )

    async def _start(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """启动容器"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would start container: {container_id}",
                simulated=True,
            )

        # 使用 docker start 命令
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker start {container_id}"},
        )

        if not result.success:
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to start container: {result.message}",
            )

        return WorkerResult(
            success=True,
            message=f"Container {container_id} started successfully",
            task_completed=True,
        )

    async def _stats(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """获取容器资源统计"""
        container_id = args.get("container_id")
        if not isinstance(container_id, str):
            return WorkerResult(success=False, message="container_id must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would get stats for container: {container_id}",
                simulated=True,
            )

        # 使用 docker stats 命令（--no-stream 只获取一次）
        result = await self._shell.execute(
            "execute_command",
            {"command": f"docker stats --no-stream --format '{{{{json .}}}}' {container_id}"},
        )

        if not result.success:
            error_msg = result.message.lower()
            if "no such" in error_msg or "not found" in error_msg:
                return WorkerResult(
                    success=False,
                    message=f"Container not found: {container_id}",
                )
            return WorkerResult(
                success=False,
                message=f"Failed to get stats: {result.message}",
            )

        # 解析 JSON 输出
        raw_output = result.data.get("raw_output", "") if result.data else ""
        if isinstance(raw_output, str) and raw_output.strip():
            try:
                stats = json.loads(raw_output.strip())

                # 提取 CPU 百分比（如 "12.34%"）
                cpu_str = stats.get("CPUPerc", "0%").rstrip("%")
                try:
                    cpu_percent = int(float(cpu_str))
                except ValueError:
                    cpu_percent = 0

                # 提取内存使用（如 "123.4MiB / 1.5GiB"）
                mem_usage_str = stats.get("MemUsage", "0MiB / 0MiB")
                mem_parts = mem_usage_str.split(" / ")

                def parse_memory(s: str) -> int:
                    """解析内存字符串为 MB"""
                    s = s.strip()
                    if s.endswith("GiB"):
                        return int(float(s.rstrip("GiB")) * 1024)
                    elif s.endswith("MiB"):
                        return int(float(s.rstrip("MiB")))
                    elif s.endswith("KiB"):
                        return int(float(s.rstrip("KiB")) / 1024)
                    return 0

                mem_usage = parse_memory(mem_parts[0]) if len(mem_parts) > 0 else 0
                mem_limit = parse_memory(mem_parts[1]) if len(mem_parts) > 1 else 0

                data: dict[str, str | int] = {
                    "cpu_percent": cpu_percent,
                    "memory_usage_mb": mem_usage,
                    "memory_limit_mb": mem_limit,
                }

                return WorkerResult(
                    success=True,
                    data=cast(dict[str, str | int], data),
                    message=f"Container {container_id}: CPU {cpu_percent}%, Memory {mem_usage}/{mem_limit}MB",
                    task_completed=True,
                )
            except json.JSONDecodeError:
                pass

        return WorkerResult(
            success=False,
            message="Failed to parse container stats",
        )
