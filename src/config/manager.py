"""配置文件管理模块"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from src.types import RiskLevel


class LLMConfig(BaseModel):
    """LLM 配置"""

    base_url: str = Field(default="http://localhost:11434/v1", description="LLM API 端点")
    model: str = Field(default="qwen2.5:7b", description="模型名称")
    api_key: str = Field(default="", description="API 密钥")
    timeout: int = Field(default=30, description="超时时间(秒)")
    max_tokens: int = Field(default=2048, description="最大 token 数")
    temperature: float = Field(default=0.2, description="采样温度（建议 0-0.3）")


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


class OpsAIConfig(BaseModel):
    """OpsAI 完整配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tui: TUIConfig = Field(default_factory=TUIConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)


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
