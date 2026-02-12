"""DeployExecutor 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.types import WorkerResult
from src.workers.deploy.executor import DeployExecutor


class TestDeployExecutor:
    """DeployExecutor 行为测试"""

    @pytest.mark.asyncio
    async def test_start_docker_desktop_waits_until_ready(self) -> None:
        shell = MagicMock()
        shell.execute = AsyncMock(
            side_effect=[
                WorkerResult(success=True, message="open ok"),
                WorkerResult(success=False, message="daemon not ready"),
                WorkerResult(success=True, message="docker ready"),
            ]
        )
        diagnoser = MagicMock()

        executor = DeployExecutor(shell, diagnoser)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            success, message = await executor.execute_with_retry(
                step={"description": "启动 Docker Desktop", "command": "open -a Docker"},
                project_dir="/tmp",
                project_type="docker",
                known_files=[],
            )

        assert success is True
        assert "启动 Docker Desktop" in message

    @pytest.mark.asyncio
    async def test_start_docker_desktop_reports_not_ready(self) -> None:
        shell = MagicMock()
        shell.execute = AsyncMock(return_value=WorkerResult(success=True, message="open ok"))
        diagnoser = MagicMock()

        executor = DeployExecutor(shell, diagnoser)

        with patch.object(executor, "_wait_for_docker_ready", new=AsyncMock(return_value=False)):
            success, message = await executor.execute_with_retry(
                step={"description": "启动 Docker Desktop", "command": "open -a Docker"},
                project_dir="/tmp",
                project_type="docker",
                known_files=[],
            )

        assert success is False
        assert "未就绪" in message
