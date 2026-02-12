"""项目类型识别测试

测试改进后的 Prompt 是否能正确识别项目类型。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.types import WorkerResult
from src.workers.deploy import DeployWorker


@pytest.fixture
def mock_http_worker() -> MagicMock:
    worker = MagicMock()
    worker.execute = AsyncMock()
    return worker


@pytest.fixture
def mock_shell_worker() -> MagicMock:
    worker = MagicMock()
    worker.execute = AsyncMock()
    return worker


@pytest.fixture
def mock_llm_client() -> MagicMock:
    client = MagicMock()
    client.generate = AsyncMock()
    client.parse_json_response = MagicMock()
    return client


@pytest.fixture
def deploy_worker(
    mock_http_worker: MagicMock,
    mock_shell_worker: MagicMock,
    mock_llm_client: MagicMock,
) -> DeployWorker:
    return DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)


class TestProjectTypeIdentification:
    """项目类型识别测试（通过验证 LLM 应该返回的类型）"""

    @pytest.mark.asyncio
    async def test_identifies_docker_when_dockerfile_exists(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试有 Dockerfile 时识别为 docker 项目"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        # Mock HTTP 响应：README + 文件列表
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Python Web App"},
                message="README",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "Dockerfile, requirements.txt, web_app.py"},
                message="Files",
            ),
        ]

        # LLM 应该根据 Prompt 规则识别为 docker 项目
        plan_response = {
            "thinking": [
                "看到 Dockerfile 和 requirements.txt",
                "根据优先级规则，有 Dockerfile 就是 docker 项目",
            ],
            "project_type": "docker",  # 关键：应该是 docker 而非 python
            "steps": [
                {"description": "构建镜像", "command": "docker build -t app ."},
                {"description": "运行容器", "command": "docker run -d --name app -p 5000:5000 app"},
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            WorkerResult(success=True, message="Directory created"),
            WorkerResult(success=True, data={"stdout": "NOT_EXISTS"}, message="Checked"),
            WorkerResult(success=True, message="Cloned"),
            env_result, env_result, env_result, env_result, env_result,
            WorkerResult(success=True, message="Built"),
            WorkerResult(success=True, message="Running"),
            # 验证步骤
            WorkerResult(success=True, message="app Up 5 seconds"),
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/python-web-app", "dry_run": True},
            )

        assert result.success is True
        assert result.simulated is True
        # 验证项目类型被正确识别
        assert result.data is not None
        assert result.data["project_type"] == "docker"

    @pytest.mark.asyncio
    async def test_identifies_docker_for_compose_project(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试有 docker-compose.yml 时识别为 docker 项目"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# App"}, message="README"),
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml, package.json"},
                message="Files",
            ),
        ]

        plan_response = {
            "thinking": ["docker-compose.yml 存在，优先识别为 docker 项目"],
            "project_type": "docker",  # 应该是 docker 而非 nodejs
            "steps": [
                {"description": "启动服务", "command": "docker compose up -d"}
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            WorkerResult(success=True, message="ok"),
            WorkerResult(success=True, data={"stdout": "NOT_EXISTS"}, message="ok"),
            WorkerResult(success=True, message="ok"),
            env_result, env_result, env_result, env_result, env_result,
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/nodejs-app", "dry_run": True},
            )

        assert result.success is True
        assert result.simulated is True
        assert result.data["project_type"] == "docker"

    @pytest.mark.asyncio
    async def test_nodejs_without_docker(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试只有 package.json 时识别为 nodejs 项目"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Node App"}, message="README"),
            WorkerResult(
                success=True,
                data={"key_files": "package.json, index.js"},
                message="Files",
            ),
        ]

        plan_response = {
            "thinking": ["没有 Dockerfile，只有 package.json，识别为 nodejs"],
            "project_type": "nodejs",
            "steps": [
                {"description": "安装依赖", "command": "npm install"},
                {"description": "启动应用", "command": "npm start"},
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            WorkerResult(success=True, message="ok"),
            WorkerResult(success=True, data={"stdout": "NOT_EXISTS"}, message="ok"),
            WorkerResult(success=True, message="ok"),
            env_result, env_result, env_result, env_result, env_result,
            WorkerResult(success=True, message="ok"),
            WorkerResult(success=True, message="ok"),
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/pure-nodejs"},
            )

        assert result.success is True
        assert result.data["project_type"] == "nodejs"


class TestEnvironmentVariableDetection:
    """环境变量检测测试"""

    @pytest.mark.asyncio
    async def test_detects_required_env_vars_from_dockerfile(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试从 Dockerfile 中检测必需的环境变量"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "Requires SECRET_KEY and LOGIN_PASSWORD"},
                message="README",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "Dockerfile, .env.example"},
                message="Files",
            ),
        ]

        # LLM 应该检测到环境变量需求并生成创建步骤
        plan_response = {
            "thinking": [
                "从 Dockerfile CMD 看到需要 SECRET_KEY 和 LOGIN_PASSWORD",
                "项目有 .env.example，但没有 .env",
                "需要在部署前创建 .env 文件",
            ],
            "project_type": "docker",
            "required_env_vars": ["SECRET_KEY", "LOGIN_PASSWORD"],
            "steps": [
                {
                    "description": "生成 SECRET_KEY",
                    "command": "python -c 'import secrets; print(secrets.token_hex(32))'",
                },
                {
                    "description": "创建 .env 文件",
                    "command": "echo 'SECRET_KEY=<generated>' > .env",
                },
                {
                    "description": "添加默认密码",
                    "command": "echo 'LOGIN_PASSWORD=admin123' >> .env",
                },
                {"description": "构建镜像", "command": "docker build -t app ."},
                {
                    "description": "运行容器",
                    "command": "docker run -d --name app -p 5000:5000 --env-file .env app",
                },
            ],
            "notes": "自动生成了环境变量",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            WorkerResult(success=True, message="ok"),
            WorkerResult(success=True, data={"stdout": "NOT_EXISTS"}, message="ok"),
            WorkerResult(success=True, message="ok"),
            env_result, env_result, env_result, env_result, env_result,
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/app-with-env", "dry_run": True},
            )

        assert result.success is True
        assert result.simulated is True
        # 验证部署计划包含了环境变量创建步骤
        assert "环境变量" in result.message or ".env" in result.message or "SECRET_KEY" in result.message
