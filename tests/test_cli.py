"""CLI 测试"""

import asyncio
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from src.cli import _deploy_project, app
from src.config.manager import OpsAIConfig
from src.llm.client import LLMClient
from src.types import Instruction, WorkerResult

runner = CliRunner()


class TestCLI:
    """测试 CLI"""

    def test_version(self) -> None:
        """测试版本命令"""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.stdout

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

    @patch("src.cli.OrchestratorEngine.react_loop_graph", new_callable=AsyncMock)
    def test_query_command(self, mock_react_loop_graph: AsyncMock) -> None:
        """测试查询命令"""
        mock_react_loop_graph.return_value = "Disk 50% used"

        result = runner.invoke(app, ["query", "检查磁盘"])

        assert result.exit_code == 0
        mock_react_loop_graph.assert_called_once()

    def test_deploy_project_initializes_deploy_worker_with_llm(self) -> None:
        """测试 _deploy_project 传入 LLMClient"""
        expected = WorkerResult(success=True, message="ok", task_completed=True)

        with (
            patch("src.cli.ConfigManager") as mock_config_manager,
            patch("src.workers.deploy.DeployWorker") as mock_deploy_worker_class,
        ):
            mock_config_manager.return_value.load.return_value = OpsAIConfig()
            mock_deploy_worker = mock_deploy_worker_class.return_value
            mock_deploy_worker.execute = AsyncMock(return_value=expected)

            result = asyncio.run(
                _deploy_project(
                    "https://github.com/example/repo",
                    "~/projects",
                    False,
                )
            )

            assert result == expected
            assert mock_deploy_worker_class.call_count == 1
            deploy_ctor_args = mock_deploy_worker_class.call_args[0]
            assert len(deploy_ctor_args) == 3
            assert isinstance(deploy_ctor_args[2], LLMClient)

    @patch("src.cli.OrchestratorEngine")
    @patch("src.cli.ConfigManager")
    @patch("src.cli.TemplateManager")
    def test_template_run_allows_high_risk_with_approval(
        self,
        mock_template_manager_class: AsyncMock,
        mock_config_manager_class: AsyncMock,
        mock_engine_class: AsyncMock,
    ) -> None:
        """测试高危操作通过审批流程执行（不再直接阻止）"""
        mock_template_manager = mock_template_manager_class.return_value
        mock_template_manager.load_template.return_value = object()
        mock_template_manager.generate_instructions.return_value = [
            Instruction(
                worker="system",
                action="delete_files",
                args={"files": ["tmp.txt"]},
                risk_level="high",
            )
        ]

        config = OpsAIConfig()
        config.safety.cli_max_risk = "high"
        config.safety.require_dry_run_for_high_risk = True
        mock_config_manager_class.return_value.load.return_value = config

        mock_engine = mock_engine_class.return_value
        mock_engine.execute_instruction = AsyncMock(
            return_value=WorkerResult(success=True, message="ok", task_completed=True)
        )

        result = runner.invoke(app, ["template", "run", "disk_cleanup"])

        # 高危操作现在会执行（通过审批），不再直接阻止
        assert result.exit_code == 0
        mock_engine.execute_instruction.assert_called_once()

    @patch("src.cli.OrchestratorEngine")
    @patch("src.cli.ConfigManager")
    @patch("src.cli.TemplateManager")
    def test_template_run_allows_high_risk_in_dry_run(
        self,
        mock_template_manager_class: AsyncMock,
        mock_config_manager_class: AsyncMock,
        mock_engine_class: AsyncMock,
    ) -> None:
        """测试模板高危操作在 dry-run 下可执行"""
        mock_template_manager = mock_template_manager_class.return_value
        mock_template_manager.load_template.return_value = object()
        mock_template_manager.generate_instructions.return_value = [
            Instruction(
                worker="system",
                action="delete_files",
                args={"files": ["tmp.txt"]},
                risk_level="high",
            )
        ]

        config = OpsAIConfig()
        config.safety.cli_max_risk = "high"
        config.safety.require_dry_run_for_high_risk = True
        mock_config_manager_class.return_value.load.return_value = config

        mock_engine = mock_engine_class.return_value
        mock_engine.execute_instruction = AsyncMock(
            return_value=WorkerResult(
                success=True,
                message="[DRY-RUN] Would delete 1 files",
                simulated=True,
                task_completed=True,
            )
        )

        result = runner.invoke(app, ["template", "run", "disk_cleanup", "--dry-run"])

        assert result.exit_code == 0
        mock_engine.execute_instruction.assert_called_once()
