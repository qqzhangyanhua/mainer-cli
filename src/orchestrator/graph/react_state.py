"""ReAct 循环状态定义"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

RiskLevel = Literal["safe", "medium", "high"]


class ReactState(TypedDict, total=False):
    """ReAct 循环状态

    使用 total=False 允许部分字段为可选
    """

    # 输入
    user_input: str
    session_id: str  # 会话 ID，用于持久化

    # LangGraph 消息历史（自动合并）
    messages: Annotated[list[dict[str, str]], add_messages]

    # 迭代控制
    iteration: int
    max_iterations: int

    # 预处理结果
    preprocessed: Optional[dict[str, object]]  # PreprocessedRequest.dict()

    # 当前指令
    current_instruction: Optional[dict[str, object]]  # Instruction.dict()
    risk_level: RiskLevel

    # Worker 执行结果
    worker_result: Optional[dict[str, object]]  # WorkerResult.dict()

    # 安全确认
    needs_approval: bool  # 是否需要人工确认
    approval_granted: bool  # 确认是否通过

    # 状态控制
    task_completed: bool
    is_error: bool

    # 错误恢复
    error_recovery_count: int  # 命令失败后回循环重试的次数

    # 权限错误建议命令
    suggested_commands: Optional[list[str]]

    # 输出
    final_message: str
    error_message: str


# 节点名称常量
NODE_START = "start"
NODE_PREPROCESS = "preprocess"
NODE_REASON = "reason"
NODE_SAFETY = "safety"
NODE_APPROVE = "approve"
NODE_EXECUTE = "execute"
NODE_CHECK = "check"
NODE_ERROR = "error"
