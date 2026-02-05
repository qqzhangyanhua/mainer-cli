"""指令校验工具"""

from __future__ import annotations

from src.types import Instruction
from src.workers.base import BaseWorker


def validate_instruction(
    instruction: Instruction,
    workers: dict[str, BaseWorker],
) -> tuple[bool, str]:
    """校验指令是否可执行

    Returns:
        (是否有效, 错误信息)
    """
    worker = workers.get(instruction.worker)
    if worker is None:
        available = ", ".join(sorted(workers.keys()))
        return False, f"Unknown worker: {instruction.worker}. Available: {available}"

    capabilities = worker.get_capabilities()
    if instruction.action not in capabilities:
        actions = ", ".join(capabilities)
        return (
            False,
            f"Unknown action: {instruction.action} for worker {instruction.worker}. "
            f"Allowed: {actions}",
        )

    return True, ""
