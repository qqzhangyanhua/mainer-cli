"""Deploy 验证系统测试

测试 Docker 容器验证、docker compose 验证、端口健康检查等功能。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.types import WorkerResult
from src.workers.deploy.executor import DeployExecutor


@pytest.fixture
def mock_shell() -> MagicMock:
    """创建模拟的 ShellWorker"""
    worker = MagicMock()
    worker.execute = AsyncMock()
    return worker


@pytest.fixture
def mock_diagnoser() -> MagicMock:
    """创建模拟的 DeployDiagnoser"""
    diagnoser = MagicMock()
    diagnoser.react_diagnose_loop = AsyncMock()
    return diagnoser


@pytest.fixture
def executor(mock_shell: MagicMock, mock_diagnoser: MagicMock) -> DeployExecutor:
    """创建 DeployExecutor 实例"""
    return DeployExecutor(mock_shell, mock_diagnoser)


class TestDockerRunVerification:
    """docker run 方式部署的验证测试"""

    @pytest.mark.asyncio
    async def test_verify_docker_run_success(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试容器运行成功的验证"""
        deploy_steps = [
            {
                "description": "运行容器",
                "command": "docker run -d --name myapp -p 5000:5000 myapp_image",
            }
        ]

        mock_shell.execute.return_value = WorkerResult(
            success=True,
            message="myapp Up 2 minutes",
        )

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
        )

        assert success is True
        assert "验证通过" in message
        assert info is not None
        assert info["container_name"] == "myapp"

    @pytest.mark.asyncio
    async def test_verify_docker_run_container_exited(
        self,
        executor: DeployExecutor,
        mock_shell: MagicMock,
        mock_diagnoser: MagicMock,
    ) -> None:
        """测试容器退出时触发诊断和修复"""
        deploy_steps = [
            {
                "description": "运行容器",
                "command": "docker run -d --name myapp -p 5000:5000 myapp_image",
            }
        ]

        # 第一次检查：容器未运行
        # 第二次检查（docker ps -a）：容器存在但已退出
        # 第三次：获取日志
        # 第四次：执行修复命令
        # 第五次：修复后再次检查，容器运行成功
        mock_shell.execute.side_effect = [
            WorkerResult(success=True, message=""),  # docker ps: 无运行容器
            WorkerResult(success=True, message="myapp Exited (1) 1 minute ago"),  # docker ps -a
            WorkerResult(
                success=True, message="Error: environment variable SECRET_KEY required"
            ),  # logs
            WorkerResult(success=True, message="ok"),  # 执行修复命令
            WorkerResult(success=True, message="myapp Up 5 seconds"),  # 修复后检查
        ]

        # 诊断器返回修复成功
        mock_diagnoser.react_diagnose_loop.return_value = (
            True,  # fixed
            "已生成环境变量",
            ["python -c '...' > .env"],
            "docker run -d --name myapp -p 5000:5000 --env-file .env myapp_image",
            "缺少环境变量 SECRET_KEY",
        )

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
            max_fix_attempts=1,
        )

        assert success is True
        assert "验证通过" in message

    @pytest.mark.asyncio
    async def test_verify_docker_run_cannot_fix(
        self,
        executor: DeployExecutor,
        mock_shell: MagicMock,
        mock_diagnoser: MagicMock,
    ) -> None:
        """测试无法自动修复时返回失败"""
        deploy_steps = [
            {
                "description": "运行容器",
                "command": "docker run -d --name myapp -p 5000:5000 myapp_image",
            }
        ]

        mock_shell.execute.side_effect = [
            WorkerResult(success=True, message=""),  # docker ps
            WorkerResult(success=True, message="myapp Exited (1)"),  # docker ps -a
            WorkerResult(success=True, message="Fatal error: unknown"),  # logs
        ]

        mock_diagnoser.react_diagnose_loop.return_value = (
            False,  # fixed
            "无法自动修复",
            [],
            None,
            "未知错误",
        )

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
            max_fix_attempts=1,
        )

        assert success is False
        assert "启动失败" in message

    @pytest.mark.asyncio
    async def test_verify_no_container_name_skips_verification(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试无容器名称时跳过验证"""
        deploy_steps = [{"description": "构建镜像", "command": "docker build -t myapp ."}]

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
        )

        assert success is True
        assert "未检测到" in message
        assert info is None


class TestDockerComposeVerification:
    """docker compose 方式部署的验证测试"""

    @pytest.mark.asyncio
    async def test_verify_compose_success(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试 docker compose 验证成功"""
        deploy_steps = [{"description": "启动服务", "command": "docker compose up -d"}]

        mock_shell.execute.return_value = WorkerResult(
            success=True,
            message='{"Name":"myapp-web-1","State":"running"}',
        )

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
        )

        assert success is True
        assert "验证通过" in message
        assert info is not None
        assert info["deployment_type"] == "compose"

    @pytest.mark.asyncio
    async def test_verify_compose_service_not_running(
        self,
        executor: DeployExecutor,
        mock_shell: MagicMock,
        mock_diagnoser: MagicMock,
    ) -> None:
        """测试 docker compose 服务未运行时的修复"""
        deploy_steps = [{"description": "启动服务", "command": "docker compose up -d"}]

        mock_shell.execute.side_effect = [
            WorkerResult(success=True, message=""),  # docker compose ps: 无服务
            WorkerResult(success=True, message="Error: SECRET_KEY required"),  # docker compose logs
            WorkerResult(success=True, message="ok"),  # 执行修复命令
            WorkerResult(success=True, message='{"State":"running"}'),  # 修复后检查
        ]

        mock_diagnoser.react_diagnose_loop.return_value = (
            True,
            "已修复环境变量",
            [],
            "docker compose up -d",
            "缺少环境变量",
        )

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
            max_fix_attempts=1,
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_verify_compose_with_docker_hyphen_command(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试支持 docker-compose（带连字符）命令"""
        deploy_steps = [{"description": "启动服务", "command": "docker-compose up -d"}]

        mock_shell.execute.return_value = WorkerResult(success=True, message='{"State":"running"}')

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp/test",
            project_type="docker",
            known_files=[],
        )

        assert success is True


class TestPortHealthCheck:
    """端口健康检查测试"""

    @pytest.mark.asyncio
    async def test_port_health_check_success_200(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试端口健康检查成功（HTTP 200）"""
        mock_shell.execute.return_value = WorkerResult(success=True, message="200")

        healthy, message = await executor.check_port_health(port=5000)

        assert healthy is True
        assert "健康检查通过" in message
        assert "200" in message

    @pytest.mark.asyncio
    async def test_port_health_check_success_3xx(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试端口健康检查成功（HTTP 3xx 重定向）"""
        mock_shell.execute.return_value = WorkerResult(success=True, message="301")

        healthy, message = await executor.check_port_health(port=8080)

        assert healthy is True
        assert "健康检查通过" in message

    @pytest.mark.asyncio
    async def test_port_health_check_4xx_still_accessible(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试 HTTP 4xx 也算可访问（说明服务在运行）"""
        mock_shell.execute.return_value = WorkerResult(success=True, message="404")

        healthy, message = await executor.check_port_health(port=3000)

        assert healthy is True
        assert "可访问" in message
        assert "404" in message

    @pytest.mark.asyncio
    async def test_port_health_check_connection_refused(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试端口无法连接"""
        mock_shell.execute.side_effect = [
            WorkerResult(success=True, message="000"),  # curl 失败
            WorkerResult(success=False, message="Connection refused"),  # nc 失败
        ]

        healthy, message = await executor.check_port_health(port=9999)

        assert healthy is False
        assert "无法连接" in message or "无法访问" in message

    @pytest.mark.asyncio
    async def test_port_health_check_fallback_to_nc(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试 curl 失败时回退到 nc"""
        mock_shell.execute.side_effect = [
            WorkerResult(success=True, message="000"),  # curl 无法连接
            WorkerResult(success=True, message="Connection succeeded"),  # nc 成功
        ]

        healthy, message = await executor.check_port_health(port=6379)

        assert healthy is True
        assert "可访问" in message


class TestVerificationTrigger:
    """验证触发逻辑测试"""

    @pytest.mark.asyncio
    async def test_verification_triggers_for_docker_run(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试包含 docker run 的部署会触发验证"""
        deploy_steps = [
            {"description": "构建", "command": "docker build -t app ."},
            {"description": "运行", "command": "docker run -d --name app -p 8000:8000 app"},
        ]

        mock_shell.execute.return_value = WorkerResult(success=True, message="app Up 1 minute")

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp",
            project_type="python",  # 注意：project_type 不是 docker
            known_files=[],
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_verification_triggers_for_docker_compose(
        self, executor: DeployExecutor, mock_shell: MagicMock
    ) -> None:
        """测试包含 docker compose 的部署会触发验证"""
        deploy_steps = [{"description": "启动", "command": "docker compose up -d"}]

        mock_shell.execute.return_value = WorkerResult(success=True, message='{"State":"running"}')

        success, message, info = await executor.verify_docker_deployment(
            deploy_steps=deploy_steps,
            project_dir="/tmp",
            project_type="nodejs",  # project_type 不是 docker
            known_files=[],
        )

        assert success is True
