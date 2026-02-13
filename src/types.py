"""核心类型定义 - 严格禁止 any 类型"""

from __future__ import annotations

from typing import Literal, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field

RiskLevel = Literal["safe", "medium", "high"]

ArgValue = Union[str, int, bool, list[str], dict[str, str]]

# 支持的分析对象类型
AnalyzeTargetType = Literal[
    "docker",  # Docker 容器
    "process",  # 进程
    "port",  # 端口
    "file",  # 文件
    "systemd",  # Systemd 服务
    "network",  # 网络连接
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
    args: dict[str, ArgValue] = Field(default_factory=dict, description="参数字典")
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
    user_input: Optional[str] = Field(default=None, description="用户原始输入")


# 预处理器相关类型
PreprocessIntent = Literal[
    "explain",  # 解释/分析对象
    "list",  # 列出对象
    "execute",  # 执行操作
    "greeting",  # 问候
    "identity",  # 自我介绍
    "deploy",  # 部署项目
    "unknown",  # 未知意图
]

PreprocessConfidence = Literal["high", "medium", "low"]


class PreprocessedRequest(BaseModel):
    """预处理后的请求"""

    original_input: str = Field(..., description="原始用户输入")
    intent: PreprocessIntent = Field(default="unknown", description="识别的意图")
    confidence: PreprocessConfidence = Field(default="low", description="置信度")
    resolved_target: Optional[str] = Field(default=None, description="解析后的目标对象名称")
    target_type: Optional[AnalyzeTargetType] = Field(default=None, description="目标对象类型")
    enriched_input: Optional[str] = Field(default=None, description="增强后的输入（用于传给 LLM）")
    needs_context: bool = Field(default=False, description="是否需要先获取上下文信息")


# GitHub 文件信息（用于 list_github_files 返回）
class GitHubFileInfo(BaseModel):
    """GitHub 仓库文件信息"""

    name: str = Field(..., description="文件名")
    type: Literal["file", "dir"] = Field(..., description="类型：文件或目录")
    path: str = Field(..., description="文件路径")
    size: int = Field(default=0, description="文件大小（字节）")


def get_raw_output(result: WorkerResult) -> Optional[str]:
    """从 WorkerResult 中提取 raw_output

    消除重复的 isinstance(result.data, dict) + result.data.get("raw_output") 模式

    Args:
        result: Worker 返回的结果

    Returns:
        raw_output 字符串，不存在时返回 None
    """
    if result.data and isinstance(result.data, dict):
        raw_output = result.data.get("raw_output")
        if isinstance(raw_output, str):
            return raw_output
    return None


def is_output_truncated(result: WorkerResult) -> bool:
    """检查 WorkerResult 的输出是否被截断

    Args:
        result: Worker 返回的结果

    Returns:
        是否被截断
    """
    if result.data and isinstance(result.data, dict):
        return bool(result.data.get("truncated", False))
    return False


@runtime_checkable
class HistoryWritable(Protocol):
    """可写历史视图的协议，兼容 RichLog 和 HistoryWriter"""

    def write(self, content: object) -> None: ...
    def clear(self) -> None: ...
