"""配置管理模块测试"""

from pathlib import Path

import pytest

from src.config.manager import ConfigManager, OpsAIConfig, LLMConfig, SafetyConfig, AuditConfig


class TestOpsAIConfig:
    """测试配置数据模型"""

    def test_default_config_creation(self) -> None:
        """测试默认配置创建"""
        config = OpsAIConfig()
        assert config.llm.base_url == "http://localhost:11434/v1"
        assert config.llm.model == "qwen2.5:7b"
        assert config.safety.cli_max_risk == "safe"
        assert config.safety.tui_max_risk == "high"

    def test_config_serialization(self) -> None:
        """测试配置序列化"""
        config = OpsAIConfig()
        json_str = config.model_dump_json()
        restored = OpsAIConfig.model_validate_json(json_str)
        assert restored == config


class TestConfigManager:
    """测试配置管理器"""

    def test_get_default_config_path(self) -> None:
        """测试默认配置路径"""
        manager = ConfigManager()
        path = manager.get_config_path()
        assert path.name == "config.json"
        assert ".opsai" in str(path)

    def test_load_creates_default_if_not_exists(self, tmp_path: Path) -> None:
        """测试配置文件不存在时创建默认配置"""
        config_path = tmp_path / ".opsai" / "config.json"
        manager = ConfigManager(config_path=config_path)
        config = manager.load()

        assert config_path.exists()
        assert config.llm.model == "qwen2.5:7b"

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """测试保存和加载往返"""
        config_path = tmp_path / ".opsai" / "config.json"
        manager = ConfigManager(config_path=config_path)

        # 修改配置
        config = OpsAIConfig(
            llm=LLMConfig(model="gpt-4o", api_key="test-key")
        )
        manager.save(config)

        # 重新加载
        loaded = manager.load()
        assert loaded.llm.model == "gpt-4o"
        assert loaded.llm.api_key == "test-key"
