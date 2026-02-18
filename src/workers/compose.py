"""Docker Compose 编排 Worker — 项目级批量操作"""

from __future__ import annotations

import json
from typing import Union, cast

from src.types import ActionParam, ArgValue, ToolAction, WorkerResult
from src.workers.base import BaseWorker
from src.workers.shell import ShellWorker


class ComposeWorker(BaseWorker):
    """Docker Compose 编排 Worker

    支持的操作:
    - status: 列出 compose 项目中所有服务及状态
    - health: 批量健康检查所有服务
    - logs: 聚合多服务日志
    - restart: 按依赖顺序重启服务
    - up: 启动 compose 项目
    - down: 停止并移除 compose 项目
    """

    def __init__(self) -> None:
        self._shell = ShellWorker()

    @property
    def name(self) -> str:
        return "compose"

    @property
    def description(self) -> str:
        return "Docker Compose management: status, health, logs, restart, up, down"

    def get_capabilities(self) -> list[str]:
        return ["status", "health", "logs", "restart", "up", "down"]

    def get_actions(self) -> list[ToolAction]:
        return [
            ToolAction(
                name="status",
                description="List all services and their state in a Compose project.",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p). Empty for auto.", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="health",
                description="Run health check on all Compose services.",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p)", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="logs",
                description="Aggregate logs from one or all services in a Compose project.",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p)", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                    ActionParam(name="service", param_type="string", description="Specific service name. Empty for all.", required=False),
                    ActionParam(name="tail", param_type="integer", description="Number of trailing log lines. Default 100.", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="restart",
                description="Restart services (respects dependency order).",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p)", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                    ActionParam(name="service", param_type="string", description="Service to restart. Empty for all.", required=False),
                ],
                risk_level="medium",
            ),
            ToolAction(
                name="up",
                description="Start the Compose project (creates containers if needed).",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p)", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                    ActionParam(name="detach", param_type="boolean", description="Run in background. Default true.", required=False),
                ],
                risk_level="medium",
            ),
            ToolAction(
                name="down",
                description="Stop and remove containers, networks for the Compose project.",
                params=[
                    ActionParam(name="project", param_type="string", description="Project name (-p)", required=False),
                    ActionParam(name="file", param_type="string", description="Compose file path (-f)", required=False),
                ],
                risk_level="high",
            ),
        ]

    async def _detect_compose_cmd(self) -> str:
        """检测 docker compose 命令格式（v2 优先）"""
        result = await self._shell.execute(
            "execute_command", {"command": "docker compose version"}
        )
        if result.success:
            return "docker compose"

        result = await self._shell.execute(
            "execute_command", {"command": "docker-compose version"}
        )
        if result.success:
            return "docker-compose"

        return ""

    def _build_cmd(
        self, base: str, project: str, file: str, subcmd: str
    ) -> str:
        """构建 compose 命令字符串"""
        parts = [base]
        if file:
            parts.append(f"-f {file}")
        if project:
            parts.append(f"-p {project}")
        parts.append(subcmd)
        return " ".join(parts)

    async def execute(
        self, action: str, args: dict[str, ArgValue]
    ) -> WorkerResult:
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        handlers = {
            "status": self._status,
            "health": self._health,
            "logs": self._logs,
            "restart": self._restart,
            "up": self._up,
            "down": self._down,
        }
        handler = handlers.get(action)
        if handler is None:
            return WorkerResult(success=False, message=f"Unknown action: {action}")

        if not dry_run:
            compose_cmd = await self._detect_compose_cmd()
            if not compose_cmd:
                return WorkerResult(
                    success=False,
                    message="docker compose 未找到。请安装 Docker Compose。",
                )
            args["_compose_cmd"] = compose_cmd
        else:
            args["_compose_cmd"] = "docker compose"

        return await handler(args, dry_run=dry_run)

    async def _status(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """列出 compose 项目所有服务状态"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would list compose services (project={project or 'auto'})",
                simulated=True,
            )

        cmd = self._build_cmd(compose_cmd, project, file, "ps --format json")
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(
                success=False,
                message=f"获取 compose 状态失败: {result.message}",
            )

        raw = result.data.get("raw_output", "") if result.data else ""
        services = self._parse_compose_ps(str(raw))

        if not services:
            return WorkerResult(
                success=True,
                message="未找到运行中的 compose 服务。",
                task_completed=True,
            )

        lines = [f"Compose 项目包含 {len(services)} 个服务:"]
        for svc in services:
            status_icon = "+" if svc.get("state") == "running" else "-"
            lines.append(
                f"  [{status_icon}] {svc.get('name', '?')} "
                f"({svc.get('image', '?')}) - {svc.get('state', '?')}"
            )

        return WorkerResult(
            success=True,
            data=services,
            message="\n".join(lines),
            task_completed=True,
        )

    async def _health(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """批量健康检查所有服务"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        if dry_run:
            return WorkerResult(
                success=True,
                message="[DRY-RUN] Would run health check on all compose services",
                simulated=True,
            )

        # 获取服务列表
        cmd = self._build_cmd(compose_cmd, project, file, "ps --format json")
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"获取服务列表失败: {result.message}")

        raw = result.data.get("raw_output", "") if result.data else ""
        services = self._parse_compose_ps(str(raw))

        if not services:
            return WorkerResult(
                success=True, message="未找到 compose 服务。", task_completed=True
            )

        # 逐服务检查健康状态
        healthy = 0
        unhealthy = 0
        lines = ["服务健康检查:"]

        for svc in services:
            svc_name = str(svc.get("name", ""))
            state = str(svc.get("state", ""))
            health = str(svc.get("health", ""))

            if state == "running":
                if health == "unhealthy":
                    unhealthy += 1
                    lines.append(f"  [!] {svc_name}: unhealthy")
                else:
                    healthy += 1
                    lines.append(f"  [+] {svc_name}: healthy")
            else:
                unhealthy += 1
                lines.append(f"  [-] {svc_name}: {state}")

        summary = f"\n总计: {healthy} 正常, {unhealthy} 异常 / {len(services)} 个服务"
        lines.append(summary)

        return WorkerResult(
            success=unhealthy == 0,
            data=services,
            message="\n".join(lines),
            task_completed=True,
        )

    async def _logs(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """聚合多服务日志"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        service = str(args.get("service", ""))
        tail = args.get("tail", 100)
        if not isinstance(tail, int):
            tail = 100
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        if dry_run:
            svc_desc = service or "all services"
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would fetch logs from {svc_desc} (tail={tail})",
                simulated=True,
            )

        subcmd = f"logs --tail {tail} --timestamps"
        if service:
            subcmd += f" {service}"

        cmd = self._build_cmd(compose_cmd, project, file, subcmd)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"获取日志失败: {result.message}")

        raw = result.data.get("raw_output", "") if result.data else ""
        log_lines = str(raw).strip().split("\n") if raw else []

        return WorkerResult(
            success=True,
            data={"raw_output": str(raw), "line_count": len(log_lines)},
            message=f"获取 {len(log_lines)} 行日志",
            task_completed=False,  # 让 LLM 总结日志内容
        )

    async def _restart(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """重启 compose 服务（按依赖顺序）"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        service = str(args.get("service", ""))
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        svc_desc = service or "所有服务"

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would restart: {svc_desc}",
                simulated=True,
            )

        subcmd = f"restart {service}".strip()
        cmd = self._build_cmd(compose_cmd, project, file, subcmd)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"重启失败: {result.message}")

        return WorkerResult(
            success=True,
            message=f"{svc_desc} 已重启",
            task_completed=True,
        )

    async def _up(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """启动 compose 项目"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        detach = args.get("detach", True)
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        subcmd = "up"
        if detach:
            subcmd += " -d"

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would run: {compose_cmd} {subcmd}",
                simulated=True,
            )

        cmd = self._build_cmd(compose_cmd, project, file, subcmd)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"启动失败: {result.message}")

        return WorkerResult(
            success=True,
            message="Compose 项目已启动",
            task_completed=True,
        )

    async def _down(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """停止并移除 compose 项目"""
        project = str(args.get("project", ""))
        file = str(args.get("file", ""))
        compose_cmd = str(args.get("_compose_cmd", "docker compose"))

        if dry_run:
            return WorkerResult(
                success=True,
                message="[DRY-RUN] Would stop and remove compose project",
                simulated=True,
            )

        cmd = self._build_cmd(compose_cmd, project, file, "down")
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"停止失败: {result.message}")

        return WorkerResult(
            success=True,
            message="Compose 项目已停止并移除",
            task_completed=True,
        )

    @staticmethod
    def _parse_compose_ps(raw: str) -> list[dict[str, Union[str, int]]]:
        """解析 docker compose ps --format json 输出"""
        services: list[dict[str, Union[str, int]]] = []
        if not raw.strip():
            return services

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                services.append({
                    "name": data.get("Name", data.get("Service", "")),
                    "service": data.get("Service", ""),
                    "state": data.get("State", data.get("Status", "")).lower().split()[0]
                    if data.get("State", data.get("Status", ""))
                    else "unknown",
                    "image": data.get("Image", ""),
                    "ports": data.get("Ports", data.get("Publishers", "")),
                    "health": data.get("Health", ""),
                })
            except (json.JSONDecodeError, IndexError):
                continue

        return services
