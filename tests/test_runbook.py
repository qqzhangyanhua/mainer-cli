"""RunbookExecutor 单元测试"""

from __future__ import annotations

import pytest

from src.templates.executor import RunbookExecutor, RunbookResult
from src.templates.manager import TaskTemplate, TemplateStep
from src.types import Instruction, WorkerResult


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------


def make_template(steps: list[TemplateStep], name: str = "test") -> TaskTemplate:
    return TaskTemplate(name=name, description="test", steps=steps)


async def success_executor(instruction: Instruction) -> WorkerResult:
    return WorkerResult(
        success=True,
        message=f"OK: {instruction.action}",
        data={"result": "done"},
    )


async def failure_executor(instruction: Instruction) -> WorkerResult:
    return WorkerResult(success=False, message=f"FAIL: {instruction.action}")


# ------------------------------------------------------------------
# 基础执行
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_execution() -> None:
    template = make_template([
        TemplateStep(worker="system", action="check_disk_usage", args={"path": "/"}),
        TemplateStep(worker="system", action="find_large_files", args={"path": "/var/log"}),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert result.success is True
    assert len(result.steps) == 2
    assert result.aborted_at is None


@pytest.mark.asyncio
async def test_empty_template() -> None:
    template = make_template([])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert result.success is True
    assert len(result.steps) == 0


# ------------------------------------------------------------------
# 失败处理: abort
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_on_failure() -> None:
    template = make_template([
        TemplateStep(worker="w", action="step1", on_failure="abort"),
        TemplateStep(worker="w", action="step2"),
    ])
    executor = RunbookExecutor(execute_fn=failure_executor)
    result = await executor.run(template)
    assert result.success is False
    assert len(result.steps) == 1  # step2 没执行
    assert result.aborted_at == 0


# ------------------------------------------------------------------
# 失败处理: skip
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_on_failure() -> None:
    call_log: list[str] = []

    async def mixed_executor(instruction: Instruction) -> WorkerResult:
        call_log.append(instruction.action)
        if instruction.action == "fail_step":
            return WorkerResult(success=False, message="failed")
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(worker="w", action="fail_step", on_failure="skip"),
        TemplateStep(worker="w", action="next_step"),
    ])
    executor = RunbookExecutor(execute_fn=mixed_executor)
    result = await executor.run(template)
    assert len(result.steps) == 2
    assert call_log == ["fail_step", "next_step"]
    assert result.aborted_at is None


# ------------------------------------------------------------------
# 重试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_then_succeed() -> None:
    attempt_count = 0

    async def flaky_executor(instruction: Instruction) -> WorkerResult:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            return WorkerResult(success=False, message="transient error")
        return WorkerResult(success=True, message="ok finally")

    template = make_template([
        TemplateStep(worker="w", action="flaky", retry_count=3),
    ])
    executor = RunbookExecutor(execute_fn=flaky_executor)
    result = await executor.run(template)
    assert result.success is True
    assert attempt_count == 3


@pytest.mark.asyncio
async def test_retry_all_fail() -> None:
    template = make_template([
        TemplateStep(worker="w", action="always_fail", retry_count=2, on_failure="abort"),
    ])
    executor = RunbookExecutor(execute_fn=failure_executor)
    result = await executor.run(template)
    assert result.success is False
    assert "3 次尝试均失败" in result.steps[0].message


# ------------------------------------------------------------------
# 条件分支
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_skip() -> None:
    """条件不满足时跳过步骤"""
    template = make_template([
        TemplateStep(worker="w", action="step1", output_key="s1"),
        TemplateStep(
            worker="w", action="recovery",
            condition="s1.success == false",
            description="仅在 step1 失败时执行",
        ),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert len(result.steps) == 2
    assert result.steps[1].skipped is True


@pytest.mark.asyncio
async def test_condition_execute() -> None:
    """条件满足时执行步骤"""
    call_log: list[str] = []

    async def logging_executor(instruction: Instruction) -> WorkerResult:
        call_log.append(instruction.action)
        if instruction.action == "step1":
            return WorkerResult(success=False, message="failed")
        return WorkerResult(success=True, message="recovered")

    template = make_template([
        TemplateStep(worker="w", action="step1", output_key="s1", on_failure="skip"),
        TemplateStep(
            worker="w", action="recovery",
            condition="s1.success == false",
        ),
    ])
    executor = RunbookExecutor(execute_fn=logging_executor)
    result = await executor.run(template)
    assert "recovery" in call_log
    assert result.steps[1].success is True


@pytest.mark.asyncio
async def test_condition_simple_truthy() -> None:
    """简单条件 'key.success' 等价于 true 检查"""
    template = make_template([
        TemplateStep(worker="w", action="step1", output_key="s1"),
        TemplateStep(worker="w", action="step2", condition="s1.success"),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert result.steps[1].skipped is False


@pytest.mark.asyncio
async def test_condition_not_equal() -> None:
    """!= 条件"""
    template = make_template([
        TemplateStep(worker="w", action="step1", output_key="s1"),
        TemplateStep(worker="w", action="step2", condition="s1.success != false"),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert result.steps[1].skipped is False


# ------------------------------------------------------------------
# 数据传递: output_key + {{ref:...}}
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_passing() -> None:
    """通过 output_key 和 {{ref:}} 传递数据"""
    captured_args: dict[str, object] = {}

    async def capturing_executor(instruction: Instruction) -> WorkerResult:
        captured_args.update(instruction.args)
        if instruction.action == "get_info":
            return WorkerResult(
                success=True, message="got it",
                data={"container_id": "abc123"},
            )
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(
            worker="container", action="get_info",
            output_key="info",
        ),
        TemplateStep(
            worker="container", action="restart",
            args={"container_id": "{{ref:info.container_id}}"},
        ),
    ])
    executor = RunbookExecutor(execute_fn=capturing_executor)
    result = await executor.run(template)
    assert result.success is True
    assert captured_args.get("container_id") == "abc123"


@pytest.mark.asyncio
async def test_context_placeholder() -> None:
    """上下文变量 {{variable}} 替换"""
    captured_args: dict[str, object] = {}

    async def capturing_executor(instruction: Instruction) -> WorkerResult:
        captured_args.update(instruction.args)
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(
            worker="system", action="check_disk_usage",
            args={"path": "{{target_path}}"},
        ),
    ])
    executor = RunbookExecutor(execute_fn=capturing_executor)
    result = await executor.run(template, context={"target_path": "/data"})
    assert captured_args.get("path") == "/data"


@pytest.mark.asyncio
async def test_inline_ref() -> None:
    """内嵌引用 'prefix {{ref:x.y}} suffix'"""
    captured_args: dict[str, object] = {}

    async def capturing_executor(instruction: Instruction) -> WorkerResult:
        captured_args.update(instruction.args)
        if instruction.action == "step1":
            return WorkerResult(
                success=True, message="ok",
                data={"host": "192.168.1.1"},
            )
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(worker="w", action="step1", output_key="s1"),
        TemplateStep(
            worker="w", action="step2",
            args={"url": "http://{{ref:s1.host}}:8080"},
        ),
    ])
    executor = RunbookExecutor(execute_fn=capturing_executor)
    result = await executor.run(template)
    assert captured_args.get("url") == "http://192.168.1.1:8080"


# ------------------------------------------------------------------
# dry-run
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_injects_flag() -> None:
    captured_dry_run: list[bool] = []

    async def checking_executor(instruction: Instruction) -> WorkerResult:
        captured_dry_run.append(bool(instruction.args.get("dry_run", False)))
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(worker="w", action="step1"),
    ])
    executor = RunbookExecutor(execute_fn=checking_executor)
    await executor.run(template, dry_run=True)
    assert captured_dry_run == [True]


# ------------------------------------------------------------------
# 进度回调
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_callback() -> None:
    progress_log: list[tuple[int, int, str]] = []

    def on_progress(idx: int, total: int, desc: str) -> None:
        progress_log.append((idx, total, desc))

    template = make_template([
        TemplateStep(worker="w", action="a", description="Step A"),
        TemplateStep(worker="w", action="b", description="Step B"),
    ])
    executor = RunbookExecutor(execute_fn=success_executor, progress_fn=on_progress)
    await executor.run(template)
    assert progress_log == [(0, 2, "Step A"), (1, 2, "Step B")]


# ------------------------------------------------------------------
# RunbookResult.summary
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_all_pass() -> None:
    template = make_template([
        TemplateStep(worker="w", action="a"),
        TemplateStep(worker="w", action="b"),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert "2/2" in result.message


@pytest.mark.asyncio
async def test_summary_with_skip() -> None:
    template = make_template([
        TemplateStep(worker="w", action="a", output_key="s1"),
        TemplateStep(worker="w", action="b", condition="s1.success == false"),
    ])
    executor = RunbookExecutor(execute_fn=success_executor)
    result = await executor.run(template)
    assert "跳过" in result.message


@pytest.mark.asyncio
async def test_unresolved_ref() -> None:
    """引用不存在的步骤结果"""
    captured_args: dict[str, object] = {}

    async def cap(instruction: Instruction) -> WorkerResult:
        captured_args.update(instruction.args)
        return WorkerResult(success=True, message="ok")

    template = make_template([
        TemplateStep(
            worker="w", action="a",
            args={"x": "{{ref:nonexistent.field}}"},
        ),
    ])
    executor = RunbookExecutor(execute_fn=cap)
    await executor.run(template)
    assert "<unresolved:" in str(captured_args.get("x", ""))
