"""CLI 测试"""

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


class TestCLI:
    """测试 CLI"""

    def test_version(self) -> None:
        """测试版本命令"""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_help(self) -> None:
        """测试帮助"""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "OpsAI" in result.stdout

    def test_config_show(self) -> None:
        """测试显示配置"""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "llm" in result.stdout.lower()

    @patch("src.cli.asyncio.run")
    def test_query_command(self, mock_run: AsyncMock) -> None:
        """测试查询命令"""
        mock_run.return_value = "Disk 50% used"

        result = runner.invoke(app, ["query", "检查磁盘"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
