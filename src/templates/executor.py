"""Runbook 执行引擎 — 支持条件分支、数据传递、失败重试"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Optional, Union

from src.templates.manager import TaskTemplate, TemplateStep
from src.types import ArgValue, Instruction, WorkerResult


class StepResult:
    """单步执行结果"""

    __slots__ = ("step_index", "step_key", "success", "message", "data", "skipped")

    def __init__(
        self,
        step_index: int,
        step_key: str,
        success: bool,
        message: str,
        data: Optional[dict[str, Union[str, int, bool]]] = None,
        skipped: bool = False,
    ) -> None:
        self.step_index = step_index
        self.step_key = step_key
        self.success = success
        self.message = message
        self.data = data
        self.skipped = skipped


class RunbookResult:
    """Runbook 整体执行结果"""

    __slots__ = ("success", "steps", "aborted_at", "message")

    def __init__(self) -> None:
        self.success: bool = True
        self.steps: list[StepResult] = []
        self.aborted_at: Optional[int] = None
        self.message: str = ""

    def add(self, step_result: StepResult) -> None:
        self.steps.append(step_result)
        if not step_result.success and not step_result.skipped:
            self.success = False

    def summary(self) -> str:
        total = len(self.steps)
        passed = sum(1 for s in self.steps if s.success and not s.skipped)
        skipped = sum(1 for s in self.steps if s.skipped)
        failed = total - passed - skipped

        parts = [f"Runbook 完成: {passed}/{total} 步成功"]
        if skipped:
            parts.append(f"{skipped} 步跳过")
        if failed:
            parts.append(f"{failed} 步失败")
        if self.aborted_at is not None:
            parts.append(f"在第 {self.aborted_at + 1} 步中止")
        return ", ".join(parts)


# 执行回调类型：接收 Instruction，返回 WorkerResult
ExecuteCallback = Callable[[Instruction], Awaitable[WorkerResult]]

# 进度回调类型：(step_index, total, description)
ProgressCallback = Callable[[int, int, str], None]


class RunbookExecutor:
    """Runbook 执行引擎

    核心能力：
    - 步骤间数据传递（output_key → {{ref:step_key.field}}）
    - 条件分支（condition 表达式）
    - 失败处理（abort/skip/retry）
    - 进度回调
    """

    def __init__(
        self,
        execute_fn: ExecuteCallback,
        progress_fn: Optional[ProgressCallback] = None,
    ) -> None:
        self._execute_fn = execute_fn
        self._progress_fn = progress_fn

    async def run(
        self,
        template: TaskTemplate,
        context: Optional[dict[str, ArgValue]] = None,
        dry_run: bool = False,
    ) -> RunbookResult:
        """执行 Runbook

        Args:
            template: 模板定义
            context: 初始上下文变量
            dry_run: 是否 dry-run 模式

        Returns:
            RunbookResult 包含所有步骤结果
        """
        result = RunbookResult()
        ctx = dict(context) if context else {}
        step_results: dict[str, StepResult] = {}
        total = len(template.steps)

        for idx, step in enumerate(template.steps):
            step_key = step.output_key or f"step{idx}"

            # 进度回调
            if self._progress_fn:
                self._progress_fn(idx, total, step.description or step.action)

            # 条件检查
            if step.condition and not self._evaluate_condition(
                step.condition, step_results
            ):
                sr = StepResult(
                    step_index=idx,
                    step_key=step_key,
                    success=True,
                    message=f"条件不满足，跳过: {step.condition}",
                    skipped=True,
                )
                result.add(sr)
                step_results[step_key] = sr
                continue

            # 替换参数中的占位符和引用
            args = self._resolve_args(step.args, ctx, step_results)
            if dry_run:
                args["dry_run"] = True

            instruction = Instruction(
                worker=step.worker,
                action=step.action,
                args=args,
            )

            # 执行（含重试）
            sr = await self._execute_with_retry(
                instruction, idx, step_key, step.retry_count
            )

            # 存储结果
            step_results[step_key] = sr
            result.add(sr)

            # 更新上下文（用于后续步骤的占位符替换）
            if sr.data:
                for k, v in sr.data.items():
                    ctx[f"{step_key}.{k}"] = str(v)
            ctx[f"{step_key}.success"] = str(sr.success).lower()
            ctx[f"{step_key}.message"] = sr.message

            # 失败处理
            if not sr.success:
                if step.on_failure == "abort":
                    result.aborted_at = idx
                    break
                # "skip" 继续执行下一步

        result.message = result.summary()
        return result

    async def _execute_with_retry(
        self,
        instruction: Instruction,
        step_index: int,
        step_key: str,
        retry_count: int,
    ) -> StepResult:
        """执行指令，支持重试"""
        attempts = retry_count + 1
        last_result: Optional[WorkerResult] = None

        for attempt in range(attempts):
            worker_result = await self._execute_fn(instruction)
            last_result = worker_result

            if worker_result.success:
                data = None
                if isinstance(worker_result.data, dict):
                    data = worker_result.data
                return StepResult(
                    step_index=step_index,
                    step_key=step_key,
                    success=True,
                    message=worker_result.message,
                    data=data,
                )

            # 还有重试机会
            if attempt < retry_count:
                continue

        # 所有重试都失败
        msg = last_result.message if last_result else "Unknown error"
        if retry_count > 0:
            msg = f"[{retry_count + 1} 次尝试均失败] {msg}"

        return StepResult(
            step_index=step_index,
            step_key=step_key,
            success=False,
            message=msg,
        )

    def _resolve_args(
        self,
        args: dict[str, ArgValue],
        context: dict[str, ArgValue],
        step_results: dict[str, StepResult],
    ) -> dict[str, ArgValue]:
        """替换参数中的占位符和步骤引用

        支持两种语法：
        - {{variable}} — 从 context 中取值
        - {{ref:step_key.field}} — 从前序步骤结果中取值
        """
        resolved: dict[str, ArgValue] = {}

        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_string(value, context, step_results)
            else:
                resolved[key] = value

        return resolved

    def _resolve_string(
        self,
        value: str,
        context: dict[str, ArgValue],
        step_results: dict[str, StepResult],
    ) -> ArgValue:
        """解析字符串中的引用"""
        # 完整匹配 {{...}}
        if value.startswith("{{") and value.endswith("}}"):
            inner = value[2:-2].strip()

            # {{ref:step_key.field}} — 步骤引用
            if inner.startswith("ref:"):
                ref_path = inner[4:]
                return self._resolve_ref(ref_path, step_results)

            # {{variable}} — 上下文变量
            return context.get(inner, value)

        # 内嵌引用替换 — "prefix {{ref:x.y}} suffix"
        def replacer(match: re.Match[str]) -> str:
            inner = match.group(1).strip()
            if inner.startswith("ref:"):
                ref_val = self._resolve_ref(inner[4:], step_results)
                return str(ref_val)
            ctx_val = context.get(inner, match.group(0))
            return str(ctx_val)

        result = re.sub(r"\{\{(.+?)\}\}", replacer, value)
        return result

    @staticmethod
    def _resolve_ref(
        ref_path: str, step_results: dict[str, StepResult]
    ) -> ArgValue:
        """解析步骤引用路径 'step_key.field'"""
        parts = ref_path.split(".", 1)
        step_key = parts[0]

        sr = step_results.get(step_key)
        if sr is None:
            return f"<unresolved:{ref_path}>"

        if len(parts) == 1:
            return sr.message

        field = parts[1]
        if field == "success":
            return str(sr.success).lower()
        if field == "message":
            return sr.message
        if sr.data and field in sr.data:
            return str(sr.data[field])

        return f"<unresolved:{ref_path}>"

    @staticmethod
    def _evaluate_condition(
        condition: str, step_results: dict[str, StepResult]
    ) -> bool:
        """评估条件表达式

        支持的格式：
        - "step_key.success" → 检查步骤是否成功
        - "step_key.success == false" → 步骤失败
        - "step_key.success == true" → 步骤成功
        """
        condition = condition.strip()

        # 处理 == 比较
        if "==" in condition:
            left, right = condition.split("==", 1)
            left = left.strip()
            right = right.strip().lower()

            left_val = RunbookExecutor._get_condition_value(left, step_results)
            return left_val == right

        # 处理 != 比较
        if "!=" in condition:
            left, right = condition.split("!=", 1)
            left = left.strip()
            right = right.strip().lower()

            left_val = RunbookExecutor._get_condition_value(left, step_results)
            return left_val != right

        # 单独的 "step_key.success" → 等价于 truthy 检查
        val = RunbookExecutor._get_condition_value(condition, step_results)
        return val == "true"

    @staticmethod
    def _get_condition_value(
        path: str, step_results: dict[str, StepResult]
    ) -> str:
        """从步骤结果中获取条件值"""
        parts = path.split(".", 1)
        step_key = parts[0]

        sr = step_results.get(step_key)
        if sr is None:
            return "false"

        if len(parts) == 1:
            return str(sr.success).lower()

        field = parts[1]
        if field == "success":
            return str(sr.success).lower()
        if field == "skipped":
            return str(sr.skipped).lower()
        if sr.data and field in sr.data:
            return str(sr.data[field]).lower()

        return "false"
