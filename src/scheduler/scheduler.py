"""定时任务调度器 — 基于 cron 表达式的模板周期执行"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 调度任务状态
JobStatus = Literal["active", "paused", "finished"]


class CronField:
    """解析单个 cron 字段（分钟/小时/日/月/星期）"""

    __slots__ = ("_values",)

    def __init__(self, expr: str, min_val: int, max_val: int) -> None:
        self._values = self._parse(expr, min_val, max_val)

    def _parse(self, expr: str, min_val: int, max_val: int) -> set[int]:
        """解析 cron 字段表达式"""
        if expr == "*":
            return set(range(min_val, max_val + 1))

        values: set[int] = set()
        for part in expr.split(","):
            part = part.strip()
            if "/" in part:
                base, step_str = part.split("/", 1)
                step = int(step_str)
                if base == "*":
                    start = min_val
                else:
                    start = int(base)
                values.update(range(start, max_val + 1, step))
            elif "-" in part:
                lo, hi = part.split("-", 1)
                values.update(range(int(lo), int(hi) + 1))
            else:
                values.add(int(part))
        return values

    def matches(self, value: int) -> bool:
        return value in self._values


class CronExpr:
    """标准 5 字段 cron 表达式（分 时 日 月 星期）"""

    __slots__ = ("_minute", "_hour", "_day", "_month", "_weekday", "raw")

    def __init__(self, expression: str) -> None:
        self.raw = expression.strip()
        parts = self.raw.split()
        if len(parts) != 5:
            raise ValueError(f"cron 表达式需要 5 个字段，实际: {len(parts)}")

        self._minute = CronField(parts[0], 0, 59)
        self._hour = CronField(parts[1], 0, 23)
        self._day = CronField(parts[2], 1, 31)
        self._month = CronField(parts[3], 1, 12)
        self._weekday = CronField(parts[4], 0, 6)

    def matches(self, ts: float) -> bool:
        """检查给定时间戳是否匹配 cron 表达式"""
        t = time.localtime(ts)
        return (
            self._minute.matches(t.tm_min)
            and self._hour.matches(t.tm_hour)
            and self._day.matches(t.tm_mday)
            and self._month.matches(t.tm_mon)
            and self._weekday.matches(t.tm_wday)
        )

    def next_match(self, after: float, max_search_minutes: int = 525960) -> float:
        """找到 after 之后的下一个匹配时间戳

        Args:
            after: 起始时间戳
            max_search_minutes: 最大搜索范围（默认约 1 年）

        Returns:
            下一个匹配的时间戳（分钟对齐）
        """
        # 从下一分钟开始搜索
        t = time.localtime(after)
        base = time.mktime((t.tm_year, t.tm_mon, t.tm_mday,
                            t.tm_hour, t.tm_min + 1, 0, 0, 0, -1))

        for _ in range(max_search_minutes):
            if self.matches(base):
                return base
            base += 60.0

        raise ValueError(f"在 {max_search_minutes} 分钟内未找到匹配时间")


class ScheduledJob(BaseModel):
    """单个定时任务"""

    job_id: str = Field(..., description="任务 ID")
    name: str = Field(..., description="任务名称")
    cron: str = Field(..., description="cron 表达式（分 时 日 月 星期）")
    template_name: str = Field(..., description="关联的模板名称")
    context: dict[str, str] = Field(default_factory=dict, description="执行上下文变量")
    dry_run: bool = Field(default=False, description="是否 dry-run 模式执行")
    status: JobStatus = Field(default="active", description="任务状态")
    created_at: float = Field(default_factory=time.time, description="创建时间")
    last_run: Optional[float] = Field(default=None, description="上次执行时间")
    next_run: Optional[float] = Field(default=None, description="下次执行时间")
    run_count: int = Field(default=0, description="执行次数")
    last_success: Optional[bool] = Field(default=None, description="上次执行是否成功")
    max_runs: Optional[int] = Field(default=None, description="最大执行次数（None=无限）")


class JobRunRecord(BaseModel):
    """任务执行记录"""

    job_id: str = Field(..., description="任务 ID")
    run_at: float = Field(default_factory=time.time, description="执行时间")
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="执行结果摘要")
    duration_ms: int = Field(default=0, description="执行耗时（毫秒）")


class Scheduler:
    """定时任务调度器

    管理 cron 定时任务，将模板与时间调度绑定。
    存储路径: ~/.opsai/scheduler/

    使用方式:
    1. 创建任务绑定模板和 cron 表达式
    2. 调用 tick() 检查并执行到期任务
    3. 在 TUI/后台循环中定期调用 tick()
    """

    MAX_HISTORY = 200

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or Path.home() / ".opsai" / "scheduler"
        self._jobs_path = self._base_dir / "jobs.json"
        self._history_path = self._base_dir / "history.json"
        self._jobs: dict[str, ScheduledJob] = {}
        self._history: list[JobRunRecord] = []
        self._counter = 0
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """从磁盘加载"""
        if self._jobs_path.exists():
            try:
                with open(self._jobs_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        job = ScheduledJob.model_validate(item)
                        self._jobs[job.job_id] = job
                    self._counter = len(self._jobs)
            except (json.JSONDecodeError, ValueError):
                pass

        if self._history_path.exists():
            try:
                with open(self._history_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._history = [
                        JobRunRecord.model_validate(r) for r in data
                    ]
            except (json.JSONDecodeError, ValueError):
                pass

    def _save_jobs(self) -> None:
        data = [j.model_dump() for j in self._jobs.values()]
        with open(self._jobs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_history(self) -> None:
        data = [r.model_dump() for r in self._history]
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _next_id(self) -> str:
        self._counter += 1
        return f"job-{self._counter:04d}"

    def add_job(
        self,
        name: str,
        cron: str,
        template_name: str,
        context: Optional[dict[str, str]] = None,
        dry_run: bool = False,
        max_runs: Optional[int] = None,
    ) -> ScheduledJob:
        """添加定时任务

        Args:
            name: 任务名称
            cron: cron 表达式
            template_name: 模板名称
            context: 执行上下文
            dry_run: 是否 dry-run
            max_runs: 最大执行次数

        Returns:
            创建的 ScheduledJob
        """
        # 验证 cron 表达式
        cron_expr = CronExpr(cron)

        job_id = self._next_id()
        now = time.time()
        next_run = cron_expr.next_match(now)

        job = ScheduledJob(
            job_id=job_id,
            name=name,
            cron=cron,
            template_name=template_name,
            context=context or {},
            dry_run=dry_run,
            status="active",
            created_at=now,
            next_run=next_run,
            max_runs=max_runs,
        )
        self._jobs[job_id] = job
        self._save_jobs()
        return job

    def remove_job(self, job_id: str) -> bool:
        """删除任务"""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_jobs()
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        job = self._jobs.get(job_id)
        if job is None or job.status != "active":
            return False
        job.status = "paused"
        self._save_jobs()
        return True

    def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        job = self._jobs.get(job_id)
        if job is None or job.status != "paused":
            return False
        job.status = "active"
        # 重新计算 next_run
        cron_expr = CronExpr(job.cron)
        job.next_run = cron_expr.next_match(time.time())
        self._save_jobs()
        return True

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """获取任务详情"""
        return self._jobs.get(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[ScheduledJob]:
        """列出任务

        Args:
            status: 可选状态过滤

        Returns:
            任务列表（按 next_run 排序）
        """
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.next_run or float("inf"))

    def get_due_jobs(self, now: Optional[float] = None) -> list[ScheduledJob]:
        """获取到期待执行的任务

        Args:
            now: 当前时间戳（默认 time.time()）

        Returns:
            到期的 active 任务列表
        """
        now = now or time.time()
        due: list[ScheduledJob] = []
        for job in self._jobs.values():
            if job.status != "active":
                continue
            if job.next_run is not None and job.next_run <= now:
                due.append(job)
        return due

    def record_run(
        self,
        job_id: str,
        success: bool,
        message: str = "",
        duration_ms: int = 0,
    ) -> None:
        """记录任务执行结果

        Args:
            job_id: 任务 ID
            success: 是否成功
            message: 结果摘要
            duration_ms: 耗时毫秒
        """
        job = self._jobs.get(job_id)
        if job is None:
            return

        now = time.time()
        job.last_run = now
        job.last_success = success
        job.run_count += 1

        # 检查是否达到最大执行次数
        if job.max_runs is not None and job.run_count >= job.max_runs:
            job.status = "finished"
            job.next_run = None
        else:
            # 计算下次执行时间
            cron_expr = CronExpr(job.cron)
            job.next_run = cron_expr.next_match(now)

        self._save_jobs()

        # 记录历史
        record = JobRunRecord(
            job_id=job_id,
            run_at=now,
            success=success,
            message=message,
            duration_ms=duration_ms,
        )
        self._history.append(record)
        self._enforce_history_limit()
        self._save_history()

    def get_history(
        self, job_id: Optional[str] = None, limit: int = 20
    ) -> list[JobRunRecord]:
        """获取执行历史

        Args:
            job_id: 可选任务 ID 过滤
            limit: 返回条数

        Returns:
            执行记录列表（最新在前）
        """
        records = self._history
        if job_id:
            records = [r for r in records if r.job_id == job_id]
        return list(reversed(records[-limit:]))

    def _enforce_history_limit(self) -> None:
        """清理超出上限的历史记录"""
        while len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    @property
    def job_count(self) -> int:
        return len(self._jobs)

    @property
    def history_count(self) -> int:
        return len(self._history)
