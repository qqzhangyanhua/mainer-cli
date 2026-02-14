"""Scheduler 单元测试"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pytest

from src.scheduler.scheduler import (
    CronExpr,
    CronField,
    JobRunRecord,
    Scheduler,
    ScheduledJob,
)


# ------------------------------------------------------------------
# CronField
# ------------------------------------------------------------------


def test_cron_field_star() -> None:
    field = CronField("*", 0, 59)
    assert field.matches(0)
    assert field.matches(30)
    assert field.matches(59)


def test_cron_field_single() -> None:
    field = CronField("5", 0, 59)
    assert field.matches(5)
    assert not field.matches(6)


def test_cron_field_range() -> None:
    field = CronField("1-5", 0, 59)
    assert field.matches(1)
    assert field.matches(3)
    assert field.matches(5)
    assert not field.matches(0)
    assert not field.matches(6)


def test_cron_field_step() -> None:
    field = CronField("*/15", 0, 59)
    assert field.matches(0)
    assert field.matches(15)
    assert field.matches(30)
    assert field.matches(45)
    assert not field.matches(10)


def test_cron_field_list() -> None:
    field = CronField("1,3,5", 0, 59)
    assert field.matches(1)
    assert field.matches(3)
    assert field.matches(5)
    assert not field.matches(2)


# ------------------------------------------------------------------
# CronExpr
# ------------------------------------------------------------------


def test_cron_expr_every_minute() -> None:
    expr = CronExpr("* * * * *")
    # 任意时间都应该匹配
    assert expr.matches(time.time())


def test_cron_expr_specific_time() -> None:
    # 2024-01-15 10:30:00 Monday (weekday=0)
    ts = time.mktime((2024, 1, 15, 10, 30, 0, 0, 0, -1))
    t = time.localtime(ts)

    expr = CronExpr(f"{t.tm_min} {t.tm_hour} * * *")
    assert expr.matches(ts)


def test_cron_expr_no_match() -> None:
    # 固定到分钟=99（不可能匹配）
    expr = CronExpr("59 23 31 12 *")
    # 用一个明显不匹配的时间
    ts = time.mktime((2024, 6, 15, 10, 30, 0, 0, 0, -1))
    assert not expr.matches(ts)


def test_cron_expr_invalid_fields() -> None:
    with pytest.raises(ValueError, match="5 个字段"):
        CronExpr("* * *")


def test_cron_expr_next_match() -> None:
    # 每小时的第 0 分钟
    expr = CronExpr("0 * * * *")
    # 从 10:30 开始找
    ts = time.mktime((2024, 1, 15, 10, 30, 0, 0, 0, -1))
    next_ts = expr.next_match(ts)

    t = time.localtime(next_ts)
    assert t.tm_min == 0
    assert t.tm_hour == 11  # 下一个整点


# ------------------------------------------------------------------
# Scheduler CRUD
# ------------------------------------------------------------------


@pytest.fixture
def scheduler(tmp_path: Path) -> Scheduler:
    return Scheduler(base_dir=tmp_path / "scheduler")


def test_add_job(scheduler: Scheduler) -> None:
    job = scheduler.add_job(
        name="disk check",
        cron="0 * * * *",
        template_name="disk_cleanup",
    )
    assert job.job_id.startswith("job-")
    assert job.status == "active"
    assert job.next_run is not None
    assert scheduler.job_count == 1


def test_add_job_invalid_cron(scheduler: Scheduler) -> None:
    with pytest.raises(ValueError):
        scheduler.add_job(
            name="bad cron",
            cron="invalid",
            template_name="test",
        )


def test_remove_job(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    assert scheduler.remove_job(job.job_id) is True
    assert scheduler.job_count == 0


def test_remove_nonexistent(scheduler: Scheduler) -> None:
    assert scheduler.remove_job("job-9999") is False


def test_get_job(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    fetched = scheduler.get_job(job.job_id)
    assert fetched is not None
    assert fetched.name == "test"


def test_get_job_nonexistent(scheduler: Scheduler) -> None:
    assert scheduler.get_job("job-9999") is None


# ------------------------------------------------------------------
# 暂停 / 恢复
# ------------------------------------------------------------------


def test_pause_and_resume(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "0 * * * *", "tmpl")
    job_id = job.job_id

    assert scheduler.pause_job(job_id) is True
    paused = scheduler.get_job(job_id)
    assert paused is not None
    assert paused.status == "paused"

    assert scheduler.resume_job(job_id) is True
    resumed = scheduler.get_job(job_id)
    assert resumed is not None
    assert resumed.status == "active"
    assert resumed.next_run is not None


def test_pause_nonactive(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    scheduler.pause_job(job.job_id)
    # 再次暂停应该失败
    assert scheduler.pause_job(job.job_id) is False


def test_resume_nonpaused(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    assert scheduler.resume_job(job.job_id) is False


# ------------------------------------------------------------------
# 列表和到期检查
# ------------------------------------------------------------------


def test_list_jobs(scheduler: Scheduler) -> None:
    scheduler.add_job("a", "0 * * * *", "tmpl_a")
    scheduler.add_job("b", "30 * * * *", "tmpl_b")
    scheduler.add_job("c", "15 * * * *", "tmpl_c")

    jobs = scheduler.list_jobs()
    assert len(jobs) == 3


def test_list_jobs_filter(scheduler: Scheduler) -> None:
    job = scheduler.add_job("a", "* * * * *", "tmpl")
    scheduler.add_job("b", "* * * * *", "tmpl")
    scheduler.pause_job(job.job_id)

    active = scheduler.list_jobs(status="active")
    assert len(active) == 1

    paused = scheduler.list_jobs(status="paused")
    assert len(paused) == 1


def test_get_due_jobs(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    # 把 next_run 设为过去
    j = scheduler.get_job(job.job_id)
    assert j is not None
    j.next_run = time.time() - 60

    due = scheduler.get_due_jobs()
    assert len(due) == 1
    assert due[0].job_id == job.job_id


def test_get_due_jobs_excludes_paused(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    j = scheduler.get_job(job.job_id)
    assert j is not None
    j.next_run = time.time() - 60

    scheduler.pause_job(job.job_id)
    due = scheduler.get_due_jobs()
    assert len(due) == 0


# ------------------------------------------------------------------
# 执行记录
# ------------------------------------------------------------------


def test_record_run(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    scheduler.record_run(job.job_id, success=True, message="ok", duration_ms=150)

    j = scheduler.get_job(job.job_id)
    assert j is not None
    assert j.run_count == 1
    assert j.last_success is True
    assert j.last_run is not None


def test_record_run_updates_next(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "0 * * * *", "tmpl")
    old_next = job.next_run
    scheduler.record_run(job.job_id, success=True)

    j = scheduler.get_job(job.job_id)
    assert j is not None
    # next_run 应该被更新
    assert j.next_run is not None
    assert j.next_run >= time.time()


def test_max_runs_finishes_job(scheduler: Scheduler) -> None:
    job = scheduler.add_job("once", "* * * * *", "tmpl", max_runs=2)
    scheduler.record_run(job.job_id, success=True)
    scheduler.record_run(job.job_id, success=True)

    j = scheduler.get_job(job.job_id)
    assert j is not None
    assert j.status == "finished"
    assert j.next_run is None


def test_history(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    scheduler.record_run(job.job_id, success=True, message="run1")
    scheduler.record_run(job.job_id, success=False, message="run2")

    history = scheduler.get_history(job.job_id)
    assert len(history) == 2
    # 最新在前
    assert history[0].message == "run2"
    assert history[1].message == "run1"


def test_history_limit(scheduler: Scheduler) -> None:
    job = scheduler.add_job("test", "* * * * *", "tmpl")
    for i in range(10):
        scheduler.record_run(job.job_id, success=True, message=f"r{i}")

    history = scheduler.get_history(job.job_id, limit=3)
    assert len(history) == 3


def test_history_all_jobs(scheduler: Scheduler) -> None:
    j1 = scheduler.add_job("a", "* * * * *", "t1")
    j2 = scheduler.add_job("b", "* * * * *", "t2")
    scheduler.record_run(j1.job_id, success=True)
    scheduler.record_run(j2.job_id, success=True)

    history = scheduler.get_history()
    assert len(history) == 2


# ------------------------------------------------------------------
# 持久化
# ------------------------------------------------------------------


def test_persistence(tmp_path: Path) -> None:
    base = tmp_path / "scheduler"
    s1 = Scheduler(base_dir=base)
    job = s1.add_job("persist", "0 * * * *", "tmpl")
    s1.record_run(job.job_id, success=True, message="done")

    # 重新加载
    s2 = Scheduler(base_dir=base)
    assert s2.job_count == 1
    j = s2.get_job(job.job_id)
    assert j is not None
    assert j.name == "persist"
    assert j.run_count == 1

    history = s2.get_history()
    assert len(history) == 1


# ------------------------------------------------------------------
# 历史容量限制
# ------------------------------------------------------------------


def test_history_enforce_limit(tmp_path: Path) -> None:
    base = tmp_path / "scheduler"
    s = Scheduler(base_dir=base)
    job = s.add_job("test", "* * * * *", "tmpl")

    for i in range(Scheduler.MAX_HISTORY + 50):
        s.record_run(job.job_id, success=True, message=f"r{i}")

    assert s.history_count <= Scheduler.MAX_HISTORY


# ------------------------------------------------------------------
# 带上下文的任务
# ------------------------------------------------------------------


def test_job_with_context(scheduler: Scheduler) -> None:
    job = scheduler.add_job(
        name="targeted cleanup",
        cron="0 3 * * *",
        template_name="disk_cleanup",
        context={"path": "/var/log", "min_size_mb": "100"},
        dry_run=True,
    )
    j = scheduler.get_job(job.job_id)
    assert j is not None
    assert j.context["path"] == "/var/log"
    assert j.dry_run is True
