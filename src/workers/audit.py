"""审计日志 Worker"""

from __future__ import annotations

from datetime import datetime, timedelta
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

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_log_size_mb: int = 100,
        retain_days: int = 90,
    ) -> None:
        """初始化 AuditWorker

        Args:
            log_path: 自定义日志路径，默认为 ~/.opsai/audit.log
            max_log_size_mb: 最大日志大小（MB）
            retain_days: 日志保留天数（<=0 表示不清理）
        """
        self._log_path = log_path or Path.home() / ".opsai" / "audit.log"
        self._max_log_size_bytes = max(0, max_log_size_mb) * 1024 * 1024
        self._retain_days = retain_days

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

            # 写入前执行保留与大小控制
            self._apply_retention()
            self._shrink_if_oversized()

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

    def _apply_retention(self) -> None:
        """按保留天数清理旧日志"""
        if self._retain_days <= 0 or not self._log_path.exists():
            return

        cutoff = datetime.now() - timedelta(days=self._retain_days)

        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return

        kept_lines: list[str] = []
        changed = False

        for line in lines:
            if not line.startswith("[") or "]" not in line:
                kept_lines.append(line)
                continue

            timestamp = line[1 : line.index("]")]
            try:
                parsed_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                kept_lines.append(line)
                continue

            if parsed_time >= cutoff:
                kept_lines.append(line)
            else:
                changed = True

        if changed:
            try:
                content = "\n".join(kept_lines)
                if content:
                    content += "\n"
                self._log_path.write_text(content, encoding="utf-8")
            except OSError:
                pass

    def _shrink_if_oversized(self) -> None:
        """日志超过最大大小时保留尾部内容"""
        if self._max_log_size_bytes <= 0 or not self._log_path.exists():
            return

        try:
            current_size = self._log_path.stat().st_size
        except OSError:
            return

        if current_size <= self._max_log_size_bytes:
            return

        target_size = self._max_log_size_bytes // 2
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return

        kept_reversed: list[str] = []
        kept_size = 0
        for line in reversed(lines):
            line_size = len((line + "\n").encode("utf-8"))
            if kept_size + line_size > target_size and kept_reversed:
                break
            kept_reversed.append(line)
            kept_size += line_size

        kept_lines = list(reversed(kept_reversed))

        try:
            content = "\n".join(kept_lines)
            if content:
                content += "\n"
            self._log_path.write_text(content, encoding="utf-8")
        except OSError:
            pass
