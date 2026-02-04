"""聊天对话 Worker - 处理非运维类对话"""

from __future__ import annotations

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class ChatWorker(BaseWorker):
    """聊天对话 Worker

    处理问候、闲聊等非运维操作
    """

    @property
    def name(self) -> str:
        return "chat"

    def get_capabilities(self) -> list[str]:
        return ["respond"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行聊天操作"""
        if action != "respond":
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        message = args.get("message", "Hello!")
        if not isinstance(message, str):
            return WorkerResult(
                success=False,
                message="message must be a string",
            )

        return WorkerResult(
            success=True,
            message=message,
            task_completed=True,
        )
