"""Kubernetes 操作 Worker — kubectl 命令封装"""

from __future__ import annotations

import json
from typing import Union, cast

from src.types import ActionParam, ArgValue, ToolAction, WorkerResult
from src.workers.base import BaseWorker
from src.workers.shell import ShellWorker


class KubernetesWorker(BaseWorker):
    """Kubernetes 操作 Worker

    支持的操作:
    - get: 获取资源列表（pods, deployments, services 等）
    - describe: 查看资源详情
    - logs: 获取 Pod 日志
    - top: 资源使用排行
    - rollout: 部署管理（status, restart, undo）
    - scale: 副本数调整
    """

    def __init__(self) -> None:
        self._shell = ShellWorker()

    @property
    def name(self) -> str:
        return "kubernetes"

    @property
    def description(self) -> str:
        return "Kubernetes operations via kubectl: get, describe, logs, top, rollout, scale"

    def get_capabilities(self) -> list[str]:
        return ["get", "describe", "logs", "top", "rollout", "scale"]

    def get_actions(self) -> list[ToolAction]:
        return [
            ToolAction(
                name="get",
                description="Get resource list (pods, deployments, services, etc.) via kubectl.",
                params=[
                    ActionParam(name="resource", param_type="string", description="Resource type: pods, deployments, services, etc.", required=False),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                    ActionParam(name="label", param_type="string", description="Label selector (-l)", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="describe",
                description="Describe a resource in detail.",
                params=[
                    ActionParam(name="resource", param_type="string", description="Resource type (e.g. pod, deployment)", required=False),
                    ActionParam(name="name", param_type="string", description="Resource name", required=True),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="logs",
                description="Get logs from a Pod.",
                params=[
                    ActionParam(name="pod", param_type="string", description="Pod name", required=True),
                    ActionParam(name="container", param_type="string", description="Container name if multi-container pod", required=False),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                    ActionParam(name="tail", param_type="integer", description="Number of trailing lines. Default 100.", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="top",
                description="Show resource usage (CPU, memory) for pods or nodes.",
                params=[
                    ActionParam(name="resource", param_type="string", description="pods or nodes. Default pods.", required=False),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="rollout",
                description="Manage deployments: status, restart, undo, history.",
                params=[
                    ActionParam(name="subcmd", param_type="string", description="status | restart | undo | history", required=False),
                    ActionParam(name="deployment", param_type="string", description="Deployment name", required=True),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                ],
                risk_level="medium",
            ),
            ToolAction(
                name="scale",
                description="Scale deployment replica count.",
                params=[
                    ActionParam(name="deployment", param_type="string", description="Deployment name", required=True),
                    ActionParam(name="replicas", param_type="integer", description="Desired replica count", required=True),
                    ActionParam(name="namespace", param_type="string", description="Kubernetes namespace", required=False),
                ],
                risk_level="medium",
            ),
        ]

    async def _check_kubectl(self) -> bool:
        result = await self._shell.execute(
            "execute_command", {"command": "kubectl version --client --short 2>/dev/null || kubectl version --client"}
        )
        return result.success

    async def execute(
        self, action: str, args: dict[str, ArgValue]
    ) -> WorkerResult:
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        handlers = {
            "get": self._get,
            "describe": self._describe,
            "logs": self._logs,
            "top": self._top,
            "rollout": self._rollout,
            "scale": self._scale,
        }
        handler = handlers.get(action)
        if handler is None:
            return WorkerResult(success=False, message=f"Unknown action: {action}")

        if not dry_run:
            if not await self._check_kubectl():
                return WorkerResult(
                    success=False,
                    message="kubectl 未找到或未配置。请安装 kubectl 并配置集群。",
                )

        return await handler(args, dry_run=dry_run)

    def _build_cmd(
        self, subcmd: str, namespace: str, extra: str = ""
    ) -> str:
        parts = ["kubectl"]
        if namespace:
            parts.append(f"-n {namespace}")
        parts.append(subcmd)
        if extra:
            parts.append(extra)
        return " ".join(parts)

    async def _get(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """获取资源列表"""
        resource = str(args.get("resource", "pods"))
        namespace = str(args.get("namespace", ""))
        label = str(args.get("label", ""))

        subcmd = f"get {resource} -o wide"
        if label:
            subcmd += f" -l {label}"

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl get {resource}",
                simulated=True,
            )

        cmd = self._build_cmd(subcmd, namespace)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"获取 {resource} 失败: {result.message}")

        raw = result.data.get("raw_output", "") if result.data else ""
        return WorkerResult(
            success=True,
            data={"raw_output": str(raw)},
            message=f"kubectl get {resource}:\n{str(raw).strip()}",
            task_completed=False,
        )

    async def _describe(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """查看资源详情"""
        resource = str(args.get("resource", "pod"))
        name = str(args.get("name", ""))
        namespace = str(args.get("namespace", ""))

        if not name:
            return WorkerResult(success=False, message="缺少参数: name")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl describe {resource} {name}",
                simulated=True,
            )

        cmd = self._build_cmd(f"describe {resource} {name}", namespace)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(
                success=False,
                message=f"describe 失败: {result.message}",
            )

        raw = result.data.get("raw_output", "") if result.data else ""
        return WorkerResult(
            success=True,
            data={"raw_output": str(raw)},
            message=f"kubectl describe {resource} {name}:\n{str(raw).strip()}",
            task_completed=False,
        )

    async def _logs(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """获取 Pod 日志"""
        pod = str(args.get("pod", ""))
        container = str(args.get("container", ""))
        namespace = str(args.get("namespace", ""))
        tail = args.get("tail", 100)
        if not isinstance(tail, int):
            tail = 100

        if not pod:
            return WorkerResult(success=False, message="缺少参数: pod")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl logs {pod} --tail {tail}",
                simulated=True,
            )

        subcmd = f"logs {pod} --tail {tail} --timestamps"
        if container:
            subcmd += f" -c {container}"

        cmd = self._build_cmd(subcmd, namespace)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(success=False, message=f"获取日志失败: {result.message}")

        raw = result.data.get("raw_output", "") if result.data else ""
        return WorkerResult(
            success=True,
            data={"raw_output": str(raw)},
            message=f"Pod {pod} 日志 (tail={tail}):\n{str(raw).strip()}",
            task_completed=False,
        )

    async def _top(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """资源使用排行"""
        resource = str(args.get("resource", "pods"))
        namespace = str(args.get("namespace", ""))

        if resource not in ("pods", "nodes"):
            return WorkerResult(
                success=False, message="top 仅支持 pods 或 nodes"
            )

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl top {resource}",
                simulated=True,
            )

        cmd = self._build_cmd(f"top {resource}", namespace)
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(
                success=False, message=f"获取资源使用失败: {result.message}"
            )

        raw = result.data.get("raw_output", "") if result.data else ""
        return WorkerResult(
            success=True,
            data={"raw_output": str(raw)},
            message=f"kubectl top {resource}:\n{str(raw).strip()}",
            task_completed=True,
        )

    async def _rollout(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """部署管理"""
        subcmd = str(args.get("subcmd", "status"))
        deployment = str(args.get("deployment", ""))
        namespace = str(args.get("namespace", ""))

        if subcmd not in ("status", "restart", "undo", "history"):
            return WorkerResult(
                success=False,
                message=f"不支持的 rollout 子命令: {subcmd}。支持: status/restart/undo/history",
            )

        if not deployment:
            return WorkerResult(success=False, message="缺少参数: deployment")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl rollout {subcmd} deployment/{deployment}",
                simulated=True,
            )

        cmd = self._build_cmd(
            f"rollout {subcmd} deployment/{deployment}", namespace
        )
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(
                success=False,
                message=f"rollout {subcmd} 失败: {result.message}",
            )

        raw = result.data.get("raw_output", "") if result.data else ""
        return WorkerResult(
            success=True,
            data={"raw_output": str(raw)},
            message=f"rollout {subcmd} deployment/{deployment}:\n{str(raw).strip()}",
            task_completed=True,
        )

    async def _scale(
        self, args: dict[str, ArgValue], dry_run: bool = False
    ) -> WorkerResult:
        """副本数调整"""
        deployment = str(args.get("deployment", ""))
        replicas = args.get("replicas")
        namespace = str(args.get("namespace", ""))

        if not deployment:
            return WorkerResult(success=False, message="缺少参数: deployment")
        if not isinstance(replicas, int):
            return WorkerResult(success=False, message="缺少参数: replicas (整数)")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] kubectl scale deployment/{deployment} --replicas={replicas}",
                simulated=True,
            )

        cmd = self._build_cmd(
            f"scale deployment/{deployment} --replicas={replicas}", namespace
        )
        result = await self._shell.execute("execute_command", {"command": cmd})

        if not result.success:
            return WorkerResult(
                success=False, message=f"scale 失败: {result.message}"
            )

        return WorkerResult(
            success=True,
            message=f"deployment/{deployment} 已调整为 {replicas} 副本",
            task_completed=True,
        )
