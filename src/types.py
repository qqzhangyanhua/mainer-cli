"""核心类型定义 - 严格禁止 any 类型"""

from __future__ import annotations

from typing import Literal, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field

RiskLevel = Literal["safe", "medium", "high"]

# 监控指标状态
MonitorStatus = Literal["ok", "warning", "critical"]

# 监控检查类型
MonitorCheckType = Literal["cpu", "memory", "disk", "port", "http", "process"]


class MonitorMetric(BaseModel):
    """单项监控指标"""

    name: str = Field(..., description="指标名称，如 cpu_usage, disk_/, port_8080")
    value: float = Field(..., description="当前值")
    unit: str = Field(..., description="单位，如 percent, ms, MB")
    status: MonitorStatus = Field(..., description="状态：ok/warning/critical")
    message: str = Field(..., description="人类可读描述")

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
    "monitor",  # 系统监控快照
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


# 日志级别类型
LogLevel = Literal["ERROR", "WARN", "INFO", "DEBUG", "TRACE", "FATAL", "UNKNOWN"]


class LogEntry(BaseModel):
    """解析后的单条日志"""

    raw: str = Field(..., description="原始日志行")
    timestamp: Optional[str] = Field(default=None, description="时间戳（原始字符串）")
    level: LogLevel = Field(default="UNKNOWN", description="日志级别")
    message: str = Field(default="", description="日志消息体")
    source: Optional[str] = Field(default=None, description="日志来源（文件路径/容器名）")


class LogPatternCount(BaseModel):
    """日志模式聚合计数"""

    pattern: str = Field(..., description="日志消息模板（去数字/ID 后）")
    count: int = Field(..., description="出现次数")
    sample: str = Field(..., description="一条原始示例")
    level: LogLevel = Field(default="UNKNOWN", description="日志级别")


class LogTrendPoint(BaseModel):
    """日志趋势时间点"""

    window: str = Field(..., description="时间窗口标签，如 '09:00-09:05'")
    total: int = Field(default=0, description="该窗口内总日志数")
    errors: int = Field(default=0, description="该窗口内错误数")
    warns: int = Field(default=0, description="该窗口内警告数")


class LogAnalysis(BaseModel):
    """日志分析结果"""

    total_lines: int = Field(default=0, description="总日志行数")
    level_counts: dict[str, int] = Field(default_factory=dict, description="按级别计数")
    top_errors: list[LogPatternCount] = Field(default_factory=list, description="最频繁的错误模式")
    top_warns: list[LogPatternCount] = Field(default_factory=list, description="最频繁的警告模式")
    trend: list[LogTrendPoint] = Field(default_factory=list, description="时间趋势")
    dedup_count: int = Field(default=0, description="去重后的独立模式数")
    source: str = Field(default="", description="日志来源描述")


# 告警规则类型
AlertSeverity = Literal["warning", "critical"]


class AlertRule(BaseModel):
    """告警规则"""

    name: str = Field(..., description="规则名称")
    metric_name: str = Field(..., description="匹配的指标名（支持前缀匹配）")
    condition: Literal["gt", "lt"] = Field(default="gt", description="条件：大于/小于")
    threshold: float = Field(..., description="阈值")
    duration: int = Field(default=1, description="连续触发 N 次才告警（防抖）")
    cooldown: int = Field(default=300, description="告警后冷却时间（秒）")
    severity: AlertSeverity = Field(default="warning", description="告警严重级别")


class AlertEvent(BaseModel):
    """告警事件"""

    rule_name: str = Field(..., description="触发的规则名称")
    metric_name: str = Field(..., description="触发的指标名")
    current_value: float = Field(..., description="当前值")
    threshold: float = Field(..., description="阈值")
    severity: AlertSeverity = Field(..., description="严重级别")
    message: str = Field(..., description="告警消息")
    recovered: bool = Field(default=False, description="是否为恢复通知")


# 通知渠道类型
NotificationChannelType = Literal["webhook", "desktop"]


class NotificationChannel(BaseModel):
    """通知渠道配置"""

    type: NotificationChannelType = Field(..., description="渠道类型")
    url: Optional[str] = Field(default=None, description="Webhook URL")
    events: list[AlertSeverity] = Field(
        default_factory=lambda: ["critical"], description="订阅的事件级别"
    )
    headers: Optional[dict[str, str]] = Field(default=None, description="自定义 HTTP 头")


# SSH 远程主机配置
class HostConfig(BaseModel):
    """远程主机配置"""

    address: str = Field(..., description="主机地址（IP 或域名）")
    port: int = Field(default=22, description="SSH 端口")
    user: str = Field(default="root", description="SSH 用户名")
    key_path: Optional[str] = Field(default=None, description="SSH 私钥路径")
    labels: list[str] = Field(default_factory=list, description="标签（用于批量操作筛选）")


@runtime_checkable
class HistoryWritable(Protocol):
    """可写历史视图的协议，兼容 RichLog 和 HistoryWriter"""

    def write(self, content: object) -> None: ...
    def clear(self) -> None: ...


# ======== Worker 自文档化类型 ========


class ActionParam(BaseModel):
    """Worker Action 的参数描述"""

    name: str = Field(..., description="参数名")
    param_type: str = Field(..., description="参数类型: string, integer, boolean, array")
    description: str = Field(default="", description="参数说明")
    required: bool = Field(default=True, description="是否必填")


class ToolAction(BaseModel):
    """Worker 支持的 Action 描述"""

    name: str = Field(..., description="Action 名称")
    description: str = Field(default="", description="Action 说明")
    params: list[ActionParam] = Field(default_factory=list, description="参数列表")
    risk_level: RiskLevel = Field(default="safe", description="默认风险等级")
