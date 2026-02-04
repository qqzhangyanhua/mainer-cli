"""审计日志 Worker"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class AuditWorker(BaseWorker):
    """审计日志 Worker

    采用追加式文本文件，便于 grep 和 tail 分析
    日志格式:
    [时间戳] INPUT: <原始指令> | WORKER: <worker>.<action> | RISK: <level> | CONFIRMED: <yes/no> | EXIT: <code> | OUTPUT: <前100字符>
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        """初始化 AuditWorker

        Args:
            log_path: 自定义日志路径，默认为 ~/.opsai/audit.log
        """
        self._log_path = log_path or Path.home() / ".opsai" / "audit.log"

    @property
    def name(self) -> str:
        return "audit"

    def get_capabilities(self) -> list[str]:
        return ["log_operation"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行审计操作"""
        if action != "log_operation":
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        return await self._log_operation(args)

    async def _log_operation(
        self,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """记录操作到审计日志"""
        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        # 提取参数
        user_input = str(args.get("input", ""))
        worker = str(args.get("worker", "unknown"))
        action = str(args.get("action", "unknown"))
        risk = str(args.get("risk", "unknown"))
        confirmed = str(args.get("confirmed", "unknown"))
        exit_code = args.get("exit_code", -1)
        output = str(args.get("output", ""))[:100]  # 截取前100字符

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would log: {worker}.{action} (risk: {risk})",
                simulated=True,
                task_completed=True,
            )

        # 格式化日志行
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = (
            f"[{timestamp}] "
            f"INPUT: {user_input} | "
            f"WORKER: {worker}.{action} | "
            f"RISK: {risk} | "
            f"CONFIRMED: {confirmed} | "
            f"EXIT: {exit_code} | "
            f"OUTPUT: {output}"
        )

        try:
            # 确保目录存在
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

            # 追加写入
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")

            return WorkerResult(
                success=True,
                message="Operation logged",
                task_completed=True,
            )
        except OSError as e:
            return WorkerResult(
                success=False,
                message=f"Failed to write audit log: {e!s}",
            )
