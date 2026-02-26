"""配置文件管理模块"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from src.types import HostConfig, NotificationChannel, RiskLevel


class LLMConfig(BaseModel):
    """LLM 配置"""

    base_url: str = Field(default="http://localhost:11434/v1", description="LLM API 端点")
    model: str = Field(default="qwen2.5:7b", description="模型名称")
    api_key: str = Field(default="", description="API 密钥")
    timeout: int = Field(default=30, description="超时时间(秒)")
    max_tokens: int = Field(default=2048, description="最大 token 数")
    temperature: float = Field(default=0.2, description="采样温度（建议 0-0.3）")
    supports_function_calling: bool = Field(
        default=False, description="模型是否支持 Function Calling"
    )
    context_window: int = Field(default=8192, description="模型上下文窗口大小")
    daily_token_limit: int = Field(default=0, description="每日 token 限额（0 表示不限制）")
    token_warning_threshold: float = Field(default=0.8, description="token 使用告警阈值（0-1）")
    token_usage_path: str = Field(
        default="~/.opsai/token_usage.json",
        description="token 使用统计文件路径",
    )


class SafetyConfig(BaseModel):
    """安全配置"""

    auto_approve_safe: bool = Field(default=True, description="自动批准安全操作")
    cli_max_risk: RiskLevel = Field(default="safe", description="CLI 模式最大风险等级")
    tui_max_risk: RiskLevel = Field(default="high", description="TUI 模式最大风险等级")
    dry_run_by_default: bool = Field(default=False, description="默认启用 dry-run 模式")
    require_dry_run_for_high_risk: bool = Field(
        default=True, description="高风险操作强制先 dry-run"
    )


class AuditConfig(BaseModel):
    """审计配置"""

    log_path: str = Field(default="~/.opsai/audit.log", description="审计日志路径")
    max_log_size_mb: int = Field(default=100, description="最大日志大小(MB)")
    retain_days: int = Field(default=90, description="日志保留天数")


class HttpConfig(BaseModel):
    """HTTP 请求配置"""

    timeout: int = Field(default=30, description="请求超时时间(秒)")
    github_token: str = Field(
        default="", description="GitHub Token（可选，用于私有仓库和提高 rate limit）"
    )


class TUIConfig(BaseModel):
    """TUI 显示配置"""

    show_thinking: bool = Field(default=False, description="是否在内容区展示思考过程")


class MonitorConfig(BaseModel):
    """监控阈值配置"""

    cpu_warning: float = Field(default=80.0, description="CPU 告警阈值(%)")
    cpu_critical: float = Field(default=95.0, description="CPU 严重阈值(%)")
    memory_warning: float = Field(default=80.0, description="内存告警阈值(%)")
    memory_critical: float = Field(default=95.0, description="内存严重阈值(%)")
    disk_warning: float = Field(default=85.0, description="磁盘告警阈值(%)")
    disk_critical: float = Field(default=95.0, description="磁盘严重阈值(%)")


class NotificationConfig(BaseModel):
    """通知配置"""

    enabled: bool = Field(default=False, description="是否启用通知")
    channels: list[NotificationChannel] = Field(default_factory=list, description="通知渠道列表")
    watch_interval: int = Field(default=30, description="watch 模式采集间隔（秒）")
    alert_duration: int = Field(default=3, description="连续触发 N 次才告警（防抖）")
    alert_cooldown: int = Field(default=300, description="告警后冷却时间（秒）")


class RemoteConfig(BaseModel):
    """远程主机配置"""

    hosts: list[HostConfig] = Field(default_factory=list, description="远程主机列表")
    default_key_path: Optional[str] = Field(default=None, description="默认 SSH 私钥路径")
    connect_timeout: int = Field(default=10, description="SSH 连接超时（秒）")
    command_timeout: int = Field(default=30, description="远程命令执行超时（秒）")


class PerformanceConfig(BaseModel):
    """性能优化配置"""

    enable_command_cache: bool = Field(default=True, description="启用命令缓存")
    cache_confidence_threshold: float = Field(default=0.85, description="缓存命中置信度阈值（0-1）")


class WorkersConfig(BaseModel):
    """Worker 管理配置"""

    enabled: list[str] = Field(
        default_factory=list, description="启用的 Worker 列表（为空表示全部启用）"
    )
    disabled: list[str] = Field(default_factory=list, description="禁用的 Worker 列表")
    plugin_paths: list[str] = Field(default_factory=list, description="自定义 Worker 插件路径")

    def is_enabled(self, name: str) -> bool:
        """判断 Worker 是否启用"""
        normalized = name.strip().lower()
        disabled = {item.lower() for item in self.disabled}
        enabled = {item.lower() for item in self.enabled}
        return normalized not in disabled and (not enabled or normalized in enabled)


class OpsAIConfig(BaseModel):
    """OpsAI 完整配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tui: TUIConfig = Field(default_factory=TUIConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    workers: WorkersConfig = Field(default_factory=WorkersConfig)


class ConfigManager:
    """配置文件管理器"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """初始化配置管理器

        Args:
            config_path: 自定义配置文件路径，默认为 ~/.opsai/config.json
        """
        self._config_path = config_path

    def get_config_path(self) -> Path:
        """获取配置文件路径"""
        if self._config_path:
            return self._config_path
        return Path.home() / ".opsai" / "config.json"

    def load(self) -> OpsAIConfig:
        """加载配置，如果不存在则创建默认配置

        Returns:
            OpsAIConfig: 配置对象

        Raises:
            ValueError: 配置文件格式错误或验证失败
            OSError: 文件读取错误
        """
        config_path = self.get_config_path()

        if not config_path.exists():
            config = OpsAIConfig()
            self.save(config)
            return config

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {config_path} - {e}") from e
        except OSError as e:
            raise OSError(f"无法读取配置文件: {config_path} - {e}") from e

        try:
            return OpsAIConfig.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"配置文件验证失败: {config_path} - {e}") from e

    def save(self, config: OpsAIConfig) -> None:
        """保存配置到文件

        Args:
            config: 配置对象

        Raises:
            OSError: 文件写入错误
        """
        config_path = self.get_config_path()
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(f"无法创建配置目录: {config_path.parent} - {e}") from e

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(config.model_dump_json(indent=2))
        except OSError as e:
            raise OSError(f"无法写入配置文件: {config_path} - {e}") from e
