"""MonitorWorker - 系统资源监控（只读，risk_level=safe）"""

from __future__ import annotations

import asyncio
import time
from typing import Union

import httpx
import psutil

from src.types import ArgValue, MonitorMetric, MonitorStatus, WorkerResult
from src.workers.base import BaseWorker

# 默认阈值：(warning, critical)
_DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "cpu": (80.0, 95.0),
    "memory": (80.0, 95.0),
    "disk": (85.0, 95.0),
}


class MonitorWorker(BaseWorker):
    """系统资源监控 Worker

    所有操作均为只读，risk_level = safe。
    """

    def __init__(
        self, thresholds: Union[dict[str, tuple[float, float]], None] = None
    ) -> None:
        self._thresholds = thresholds or _DEFAULT_THRESHOLDS

    def _judge(self, value: float, category: str) -> MonitorStatus:
        """统一阈值判定，零特殊情况"""
        warn, crit = self._thresholds.get(category, (80.0, 95.0))
        if value >= crit:
            return "critical"
        if value >= warn:
            return "warning"
        return "ok"

    @property
    def name(self) -> str:
        return "monitor"

    def get_capabilities(self) -> list[str]:
        return [
            "snapshot", "check_port", "check_http",
            "check_process", "top_processes", "find_service_port",
        ]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        dry_run = bool(args.get("dry_run", False))

        dispatch: dict[str, str] = {
            "snapshot": "_snapshot",
            "check_port": "_check_port",
            "check_http": "_check_http",
            "check_process": "_check_process",
            "top_processes": "_top_processes",
            "find_service_port": "_find_service_port",
        }

        method_name = dispatch.get(action)
        if method_name is None:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would execute monitor.{action}",
                simulated=True,
            )

        method = getattr(self, method_name)
        result: WorkerResult = await method(args)
        return result

    # ------------------------------------------------------------------
    # snapshot
    # ------------------------------------------------------------------
    async def _snapshot(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        include_raw = args.get("include")
        include: Union[list[str], None] = None
        if isinstance(include_raw, list):
            include = include_raw

        metrics: list[MonitorMetric] = []

        # CPU
        if include is None or "cpu" in include:
            cpu_pct = await asyncio.to_thread(psutil.cpu_percent, interval=1)
            status = self._judge(cpu_pct, "cpu")
            metrics.append(MonitorMetric(
                name="cpu_usage",
                value=cpu_pct,
                unit="percent",
                status=status,
                message=f"CPU 使用率 {cpu_pct:.1f}%",
            ))

        # Memory
        if include is None or "memory" in include:
            mem = psutil.virtual_memory()
            mem_pct = mem.percent
            status = self._judge(mem_pct, "memory")
            used_gb = mem.used / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            metrics.append(MonitorMetric(
                name="memory_usage",
                value=mem_pct,
                unit="percent",
                status=status,
                message=f"内存 {used_gb:.1f}GB / {total_gb:.1f}GB ({mem_pct:.1f}%)",
            ))

        # Disk
        if include is None or "disk" in include:
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except PermissionError:
                    continue
                pct = usage.percent
                status = self._judge(pct, "disk")
                used_gb = usage.used / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                metrics.append(MonitorMetric(
                    name=f"disk_{part.mountpoint}",
                    value=pct,
                    unit="percent",
                    status=status,
                    message=(
                        f"磁盘 {part.mountpoint}: "
                        f"{used_gb:.1f}GB / {total_gb:.1f}GB ({pct:.1f}%)"
                    ),
                ))

        # Load average
        if include is None or "load" in include:
            load1, load5, load15 = psutil.getloadavg()
            cpu_count = psutil.cpu_count() or 1
            load_ratio = load1 / cpu_count * 100
            status = self._judge(load_ratio, "cpu")
            metrics.append(MonitorMetric(
                name="load_average",
                value=round(load1, 2),
                unit="load",
                status=status,
                message=f"负载 {load1:.2f} / {load5:.2f} / {load15:.2f} (CPU 核数: {cpu_count})",
            ))

        # 构建结构化 data
        data: list[dict[str, Union[str, int]]] = [
            {
                "name": m.name,
                "value": str(m.value),
                "unit": m.unit,
                "status": m.status,
                "message": m.message,
            }
            for m in metrics
        ]

        # 汇总状态
        worst: MonitorStatus = "ok"
        for m in metrics:
            if m.status == "critical":
                worst = "critical"
                break
            if m.status == "warning":
                worst = "warning"

        summary_map: dict[MonitorStatus, str] = {
            "ok": "系统状态正常",
            "warning": "部分指标偏高，请关注",
            "critical": "存在严重告警，请立即处理",
        }

        return WorkerResult(
            success=True,
            data=data,
            message=f"系统快照: {summary_map[worst]} ({len(metrics)} 项指标)",
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # check_port
    # ------------------------------------------------------------------
    async def _check_port(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        port_raw = args.get("port")
        if port_raw is None or not isinstance(port_raw, (str, int)):
            return WorkerResult(success=False, message="缺少参数: port")
        port = int(port_raw)

        host_raw = args.get("host", "localhost")
        host = str(host_raw)

        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            writer.close()
            await writer.wait_closed()

            metric = MonitorMetric(
                name=f"port_{port}",
                value=round(elapsed_ms, 2),
                unit="ms",
                status="ok",
                message=f"端口 {host}:{port} 可达 (响应 {elapsed_ms:.1f}ms)",
            )
            return WorkerResult(
                success=True,
                data={"name": f"port_{port}", "value": str(round(elapsed_ms, 2)),
                      "unit": "ms", "status": "ok", "message": metric.message},
                message=metric.message,
                task_completed=True,
            )
        except (OSError, asyncio.TimeoutError):
            elapsed_ms = (time.monotonic() - start) * 1000
            return WorkerResult(
                success=True,
                data={"name": f"port_{port}", "value": str(round(elapsed_ms, 2)),
                      "unit": "ms", "status": "critical",
                      "message": f"端口 {host}:{port} 不可达"},
                message=f"端口 {host}:{port} 不可达 (超时 {elapsed_ms:.0f}ms)",
                task_completed=True,
            )

    # ------------------------------------------------------------------
    # check_http
    # ------------------------------------------------------------------
    async def _check_http(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        url_raw = args.get("url")
        if url_raw is None:
            return WorkerResult(success=False, message="缺少参数: url")
        url = str(url_raw)

        timeout_raw = args.get("timeout", 5)
        timeout = int(timeout_raw) if isinstance(timeout_raw, (str, int)) else 5

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url)
            elapsed_ms = (time.monotonic() - start) * 1000
            status_code = resp.status_code

            status: MonitorStatus = "ok" if 200 <= status_code < 400 else "critical"
            msg = f"HTTP {url} → {status_code} ({elapsed_ms:.0f}ms)"

            return WorkerResult(
                success=True,
                data={"name": f"http_{url}", "status_code": status_code,
                      "latency_ms": str(round(elapsed_ms, 2)), "status": status},
                message=msg,
                task_completed=True,
            )
        except (httpx.HTTPError, OSError) as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return WorkerResult(
                success=True,
                data={"name": f"http_{url}", "status_code": 0,
                      "latency_ms": str(round(elapsed_ms, 2)), "status": "critical"},
                message=f"HTTP {url} 请求失败: {exc} ({elapsed_ms:.0f}ms)",
                task_completed=True,
            )

    # ------------------------------------------------------------------
    # check_process
    # ------------------------------------------------------------------
    async def _check_process(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        name_raw = args.get("name")
        if name_raw is None:
            return WorkerResult(success=False, message="缺少参数: name")
        proc_name = str(name_raw).lower()

        found: list[dict[str, Union[str, int]]] = []
        for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                pname: str = info.get("name", "") or ""
                if proc_name in pname.lower():
                    found.append({
                        "pid": info.get("pid", 0),
                        "name": pname,
                        "cpu_percent": str(info.get("cpu_percent", 0) or 0),
                        "memory_percent": str(
                            round(float(info.get("memory_percent", 0) or 0), 2)
                        ),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not found:
            return WorkerResult(
                success=True,
                data=None,
                message=f"未找到名称包含 '{proc_name}' 的进程",
                task_completed=True,
            )

        return WorkerResult(
            success=True,
            data=found,
            message=f"找到 {len(found)} 个匹配进程 '{proc_name}'",
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # top_processes
    # ------------------------------------------------------------------
    async def _top_processes(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        sort_by_raw = args.get("sort_by", "cpu")
        sort_by = str(sort_by_raw) if sort_by_raw in ("cpu", "memory") else "cpu"

        limit_raw = args.get("limit", 10)
        limit = int(limit_raw) if isinstance(limit_raw, (str, int)) else 10

        sort_key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
        attrs = ["name", "pid", "cpu_percent", "memory_percent"]

        procs: list[dict[str, Union[str, int]]] = []
        for proc in psutil.process_iter(attrs):
            try:
                info = proc.info
                procs.append({
                    "pid": info.get("pid", 0),
                    "name": info.get("name", "") or "",
                    "cpu_percent": str(info.get("cpu_percent", 0) or 0),
                    "memory_percent": str(
                        round(float(info.get("memory_percent", 0) or 0), 2)
                    ),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda p: float(p[sort_key]), reverse=True)
        top = procs[:limit]

        label = "CPU" if sort_by == "cpu" else "内存"
        return WorkerResult(
            success=True,
            data=top,
            message=f"按{label}排序的 Top {len(top)} 进程",
            task_completed=True,
        )

    # ------------------------------------------------------------------
    # find_service_port - 按服务名查找实际监听端口
    # ------------------------------------------------------------------
    async def _find_service_port(
        self, args: dict[str, ArgValue],
    ) -> WorkerResult:
        """按服务/进程名查找其实际监听的 TCP 端口。

        解决 LLM 默认端口偏见问题：当用户说"重启nginx"但未指定端口时，
        先调用此方法探测 nginx 实际监听的端口，而非假设 80。
        """
        name_raw = args.get("name")
        if name_raw is None:
            return WorkerResult(success=False, message="缺少参数: name (服务/进程名)")
        service_name = str(name_raw).lower()

        found: list[dict[str, Union[str, int]]] = []

        for proc in psutil.process_iter(["name", "pid", "cmdline"]):
            try:
                info = proc.info
                pname: str = (info.get("name", "") or "").lower()
                cmdline_raw = info.get("cmdline") or []
                cmdline_str = " ".join(str(c) for c in cmdline_raw).lower()

                if service_name not in pname and service_name not in cmdline_str:
                    continue

                pid = info.get("pid", 0)
                connections = proc.net_connections(kind="tcp")

                for conn in connections:
                    if conn.status == "LISTEN" and conn.laddr:
                        addr = conn.laddr
                        found.append({
                            "pid": pid,
                            "process_name": info.get("name", "") or "",
                            "listen_address": str(addr.ip),
                            "listen_port": addr.port,
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not found:
            return WorkerResult(
                success=True,
                data=None,
                message=(
                    f"未找到名称包含 '{service_name}' 的监听进程。"
                    f"服务可能未运行，或以其他用户身份运行（需 sudo 权限查看）。"
                ),
                task_completed=False,
            )

        unique_ports = sorted({int(item["listen_port"]) for item in found})
        port_list = ", ".join(str(p) for p in unique_ports)

        summary_parts = []
        seen_ports: set[int] = set()
        for item in found:
            port = int(item["listen_port"])
            if port not in seen_ports:
                seen_ports.add(port)
                summary_parts.append(
                    f"PID {item['pid']} ({item['process_name']}) "
                    f"监听 {item['listen_address']}:{port}"
                )

        return WorkerResult(
            success=True,
            data=found,
            message=(
                f"服务 '{service_name}' 实际监听端口: {port_list}\n"
                + "\n".join(summary_parts)
                + f"\n⚠️ 请使用实际端口 {port_list} 进行操作，不要使用默认端口!"
            ),
            task_completed=False,
        )
