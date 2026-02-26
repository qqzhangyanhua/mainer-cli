"""LangGraph 消息适配器 - 从 OrchestratorEngine 提取的消息转换逻辑"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional, Union, cast

from typing_extensions import TypeAlias

from src.types import ConversationEntry, Instruction, RiskLevel, WorkerResult

WorkerResultData: TypeAlias = Union[
    list[dict[str, Union[str, int]]],
    dict[str, Union[str, int, bool]],
    None,
]


def build_graph_messages(
    history: Optional[list[ConversationEntry]],
) -> list[dict[str, object]]:
    """将 ConversationEntry 转换为 LangGraph 消息格式"""
    messages: list[dict[str, object]] = []
    if not history:
        return messages

    for entry in history:
        messages.append(
            {
                "role": "assistant",
                "content": f"Execute: {entry.instruction.worker}.{entry.instruction.action}",
                "instruction": entry.instruction.dict(),
                "user_input": entry.user_input,
                "thinking": "",  # 跨会话历史不保留 thinking
            }
        )
        messages.append(
            {
                "role": "system",
                "content": entry.result.message,
                "result": entry.result.dict(),
            }
        )

    return messages


def parse_graph_messages(messages: Sequence[object]) -> list[ConversationEntry]:
    """从 LangGraph 消息历史解析 ConversationEntry"""
    history: list[ConversationEntry] = []

    def _message_role(message: object) -> Optional[str]:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", None)
        if role == "ai":
            return "assistant"
        if role == "human":
            return "user"
        return role

    def _message_get(message: object, key: str) -> object:
        if isinstance(message, dict):
            return message.get(key)
        additional = getattr(message, "additional_kwargs", None)
        if isinstance(additional, dict):
            return additional.get(key)
        return None

    i = 0
    while i < len(messages) - 1:
        msg1 = messages[i]
        msg2 = messages[i + 1]

        if _message_role(msg1) == "assistant" and _message_role(msg2) == "system":
            inst_dict = _message_get(msg1, "instruction")
            res_dict = _message_get(msg2, "result")
            if isinstance(inst_dict, dict) and isinstance(res_dict, dict):
                args = inst_dict.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                risk_level_raw = inst_dict.get("risk_level", "safe")
                risk_level: RiskLevel = (
                    risk_level_raw if risk_level_raw in {"safe", "medium", "high"} else "safe"
                )
                data_value = res_dict.get("data")
                if isinstance(data_value, (dict, list)):
                    data = cast(WorkerResultData, data_value)
                else:
                    data = None
                user_input_raw = _message_get(msg1, "user_input")
                user_input = user_input_raw if isinstance(user_input_raw, str) else None
                instruction = Instruction(
                    worker=str(inst_dict.get("worker", "")),
                    action=str(inst_dict.get("action", "")),
                    args=args,
                    risk_level=risk_level,
                    dry_run=bool(inst_dict.get("dry_run", False)),
                )
                result = WorkerResult(
                    success=bool(res_dict.get("success", False)),
                    data=data,
                    message=str(res_dict.get("message", "")),
                    task_completed=bool(res_dict.get("task_completed", False)),
                    simulated=bool(res_dict.get("simulated", False)),
                )
                history.append(
                    ConversationEntry(
                        instruction=instruction,
                        result=result,
                        user_input=user_input,
                    )
                )

        i += 2

    return history
