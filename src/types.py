"""核心类型定义 - 严格禁止 any 类型"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

RiskLevel = Literal["safe", "medium", "high"]

ArgValue = Union[str, int, bool, list[str], dict[str, str]]

# 支持的分析对象类型
AnalyzeTargetType = Literal[
    "docker",    # Docker 容器
    "process",   # 进程
    "port",      # 端口
    "file",      # 文件
    "systemd",   # Systemd 服务
    "network",   # 网络连接
]


class AnalyzeTarget(BaseModel):
    """分析对象"""

    type: AnalyzeTargetType = Field(..., description="对象类型")
    name: str = Field(..., description="对象标识符（容器名、PID、端口号等）")
    context: Optional[str] = Field(default=None, description="额外上下文信息")


class Instruction(BaseModel):
    """Orchestrator 发送给 Worker 的指令"""

    worker: str = Field(..., description="目标 Worker 标识符")
    action: str = Field(..., description="动作名称")
    args: dict[str, ArgValue] = Field(
        default_factory=dict, description="参数字典"
    )
    risk_level: RiskLevel = Field(default="safe", description="风险等级")
    dry_run: bool = Field(default=False, description="是否为模拟执行")


class WorkerResult(BaseModel):
    """Worker 返回给 Orchestrator 的结果"""

    success: bool = Field(..., description="执行是否成功")
    data: Union[
        list[dict[str, Union[str, int]]],
        dict[str, Union[str, int, bool]],  # 支持 bool 用于 truncated 标记
        None,
    ] = Field(default=None, description="结构化结果数据")
    message: str = Field(..., description="人类可读描述")
    task_completed: bool = Field(default=False, description="任务是否完成")
    simulated: bool = Field(default=False, description="是否为模拟执行结果")


class ConversationEntry(BaseModel):
    """ReAct 循环中的对话记录"""

    instruction: Instruction
    result: WorkerResult
