"""聊天对话 Worker - 处理最终回复"""

from __future__ import annotations

from src.types import ActionParam, ArgValue, ToolAction, WorkerResult
from src.workers.base import BaseWorker


class ChatWorker(BaseWorker):
    """聊天对话 Worker — 用于向用户发送最终回复"""

    @property
    def name(self) -> str:
        return "chat"

    @property
    def description(self) -> str:
        return (
            "Deliver the final answer to the user. "
            "MUST be the last action in every task. "
            "Summarize all findings in clear, structured Chinese with markdown formatting."
        )

    def get_capabilities(self) -> list[str]:
        return ["respond"]

    def get_actions(self) -> list[ToolAction]:
        return [
            ToolAction(
                name="respond",
                description=(
                    "Send a comprehensive answer to the user. "
                    "Use Chinese. Include structured findings, tables, and recommendations."
                ),
                params=[
                    ActionParam(
                        name="message",
                        param_type="string",
                        description="The final message to display to the user (Chinese, markdown)",
                        required=True,
                    ),
                ],
                risk_level="safe",
            ),
        ]

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
