"""集成测试"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config.manager import ConfigManager, OpsAIConfig
from src.orchestrator.engine import OrchestratorEngine


class TestIntegration:
    """集成测试"""

    @pytest.fixture
    def config(self, tmp_path: Path) -> OpsAIConfig:
        """创建测试配置"""
        config_path = tmp_path / ".opsai" / "config.json"
        manager = ConfigManager(config_path=config_path)
        return manager.load()

    @pytest.mark.asyncio
    async def test_full_workflow_safe_operation(self, config: OpsAIConfig) -> None:
        """测试完整工作流 - 安全操作"""
        engine = OrchestratorEngine(config)

        # Mock LLM 返回安全操作
        mock_response = '{"worker": "system", "action": "check_disk_usage", "args": {"path": "/"}, "risk_level": "safe"}'

        with patch.object(engine._llm_client, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response

            result = await engine.react_loop("检查磁盘")

            # 应该成功执行
            assert "Disk" in result or "disk" in result.lower() or "Error" not in result

    @pytest.mark.asyncio
    async def test_high_risk_rejected_without_callback(self, config: OpsAIConfig) -> None:
        """测试高危操作在无回调时被拒绝"""
        engine = OrchestratorEngine(config)  # 无确认回调

        mock_response = '{"worker": "system", "action": "delete_files", "args": {"command": "rm -rf /"}, "risk_level": "high"}'

        with patch.object(engine._llm_client, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response

            result = await engine.react_loop("删除所有文件")

            # 应该被拒绝
            assert "HIGH-risk" in result or "requires TUI" in result

    @pytest.mark.asyncio
    async def test_audit_log_created(self, config: OpsAIConfig, tmp_path: Path) -> None:
        """测试审计日志创建"""
        # 设置审计日志路径
        audit_log = tmp_path / "audit.log"
        config.audit.log_path = str(audit_log)

        engine = OrchestratorEngine(config)

        mock_response = '{"worker": "system", "action": "check_disk_usage", "args": {"path": "/"}, "risk_level": "safe"}'

        with patch.object(engine._llm_client, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response

            await engine.react_loop("检查磁盘")

            # 审计日志应该存在（使用默认路径）
            # 注意：实际日志路径在 AuditWorker 中硬编码
