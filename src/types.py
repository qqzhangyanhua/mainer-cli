"""核心类型定义 - 严格禁止 any 类型"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


RiskLevel = Literal["safe", "medium", "high"]


class Instruction(BaseModel):  # type: ignore[explicit-any]
    """Orchestrator 发送给 Worker 的指令"""

    worker: str = Field(..., description="目标 Worker 标识符")
    action: str = Field(..., description="动作名称")
    args: dict[str, Union[str, int, bool, list[str], dict[str, str]]] = Field(
        default_factory=dict, description="参数字典"
    )
    risk_level: RiskLevel = Field(default="safe", description="风险等级")


class WorkerResult(BaseModel):  # type: ignore[explicit-any]
    """Worker 返回给 Orchestrator 的结果"""

    success: bool = Field(..., description="执行是否成功")
    data: Union[list[dict[str, Union[str, int]]], dict[str, Union[str, int]], None] = Field(
        default=None, description="结构化结果数据"
    )
    message: str = Field(..., description="人类可读描述")
    task_completed: bool = Field(default=False, description="任务是否完成")


class ConversationEntry(BaseModel):  # type: ignore[explicit-any]
    """ReAct 循环中的对话记录"""

    instruction: Instruction
    result: WorkerResult
