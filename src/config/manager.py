"""配置文件管理模块"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM 配置"""

    base_url: str = Field(default="http://localhost:11434/v1", description="LLM API 端点")
    model: str = Field(default="qwen2.5:7b", description="模型名称")
    api_key: str = Field(default="", description="API 密钥")
    timeout: int = Field(default=30, description="超时时间(秒)")
    max_tokens: int = Field(default=2048, description="最大 token 数")


class SafetyConfig(BaseModel):
    """安全配置"""

    auto_approve_safe: bool = Field(default=True, description="自动批准安全操作")
    cli_max_risk: str = Field(default="safe", description="CLI 模式最大风险等级")
    tui_max_risk: str = Field(default="high", description="TUI 模式最大风险等级")


class AuditConfig(BaseModel):
    """审计配置"""

    log_path: str = Field(default="~/.opsai/audit.log", description="审计日志路径")
    max_log_size_mb: int = Field(default=100, description="最大日志大小(MB)")
    retain_days: int = Field(default=90, description="日志保留天数")


class OpsAIConfig(BaseModel):
    """OpsAI 完整配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)


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
        """
        config_path = self.get_config_path()

        if not config_path.exists():
            config = OpsAIConfig()
            self.save(config)
            return config

        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        return OpsAIConfig.model_validate(data)

    def save(self, config: OpsAIConfig) -> None:
        """保存配置到文件

        Args:
            config: 配置对象
        """
        config_path = self.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config.model_dump_json(indent=2))
