"""DeployWorker 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.types import WorkerResult
from src.workers.deploy import DeployWorker


@pytest.fixture
def mock_http_worker() -> MagicMock:
    """创建模拟的 HttpWorker"""
    worker = MagicMock()
    worker.execute = AsyncMock()
    return worker


@pytest.fixture
def mock_shell_worker() -> MagicMock:
    """创建模拟的 ShellWorker"""
    worker = MagicMock()
    worker.execute = AsyncMock()
    return worker


@pytest.fixture
def deploy_worker(mock_http_worker: MagicMock, mock_shell_worker: MagicMock) -> DeployWorker:
    """创建 DeployWorker 实例"""
    return DeployWorker(mock_http_worker, mock_shell_worker)


class TestDeployWorkerBasic:
    """基本属性测试"""

    def test_name(self, deploy_worker: DeployWorker) -> None:
        """测试 Worker 名称"""
        assert deploy_worker.name == "deploy"

    def test_capabilities(self, deploy_worker: DeployWorker) -> None:
        """测试 Worker 能力列表"""
        caps = deploy_worker.get_capabilities()
        # 新的简化能力：只暴露一键部署
        assert "deploy" in caps
        # 内部方法仍可访问但不在 capabilities 列表中
        assert len(caps) == 1

    @pytest.mark.asyncio
    async def test_unknown_action(self, deploy_worker: DeployWorker) -> None:
        """测试未知动作"""
        result = await deploy_worker.execute("unknown_action", {})
        assert not result.success
        assert "Unknown action" in result.message


class TestAnalyzeRepo:
    """analyze_repo 动作测试"""

    @pytest.mark.asyncio
    async def test_missing_repo_url(self, deploy_worker: DeployWorker) -> None:
        """测试缺少 repo_url 参数"""
        result = await deploy_worker.execute("analyze_repo", {})
        assert not result.success
        assert "repo_url parameter is required" in result.message

    @pytest.mark.asyncio
    async def test_invalid_repo_url(self, deploy_worker: DeployWorker) -> None:
        """测试无效的 GitHub URL"""
        result = await deploy_worker.execute(
            "analyze_repo",
            {"repo_url": "https://example.com/not-github"},
        )
        assert not result.success
        assert "Invalid GitHub URL" in result.message

    @pytest.mark.asyncio
    async def test_analyze_docker_project(
        self,
        deploy_worker: DeployWorker,
        mock_http_worker: MagicMock,
    ) -> None:
        """测试分析 Docker 项目"""
        # 模拟 README 获取
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Test Project\n\nA Docker-based application."},
                message="README fetched",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "Dockerfile, docker-compose.yml"},
                message="Files listed",
            ),
        ]

        result = await deploy_worker.execute(
            "analyze_repo",
            {"repo_url": "https://github.com/owner/test-repo"},
        )

        assert result.success
        assert result.data is not None
        assert result.data.get("project_type") == "docker"
        assert "docker" in result.message.lower()
        assert not result.task_completed

    @pytest.mark.asyncio
    async def test_analyze_nodejs_project(
        self,
        deploy_worker: DeployWorker,
        mock_http_worker: MagicMock,
    ) -> None:
        """测试分析 Node.js 项目"""
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Node Project"},
                message="README fetched",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "package.json"},
                message="Files listed",
            ),
        ]

        result = await deploy_worker.execute(
            "analyze_repo",
            {"repo_url": "https://github.com/owner/node-app"},
        )

        assert result.success
        assert result.data is not None
        assert result.data.get("project_type") == "nodejs"

    @pytest.mark.asyncio
    async def test_analyze_python_project(
        self,
        deploy_worker: DeployWorker,
        mock_http_worker: MagicMock,
    ) -> None:
        """测试分析 Python 项目"""
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Python Project"},
                message="README fetched",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "requirements.txt, pyproject.toml"},
                message="Files listed",
            ),
        ]

        result = await deploy_worker.execute(
            "analyze_repo",
            {"repo_url": "https://github.com/owner/python-app"},
        )

        assert result.success
        assert result.data is not None
        assert result.data.get("project_type") == "python"


class TestCloneRepo:
    """clone_repo 动作测试"""

    @pytest.mark.asyncio
    async def test_missing_repo_url(self, deploy_worker: DeployWorker) -> None:
        """测试缺少 repo_url 参数"""
        result = await deploy_worker.execute("clone_repo", {})
        assert not result.success
        assert "repo_url parameter is required" in result.message

    @pytest.mark.asyncio
    async def test_dry_run_clone(self, deploy_worker: DeployWorker) -> None:
        """测试 dry-run 模式"""
        result = await deploy_worker.execute(
            "clone_repo",
            {
                "repo_url": "https://github.com/owner/test-repo",
                "target_dir": "~/projects",
                "dry_run": True,
            },
        )

        assert result.success
        assert result.simulated
        assert "[DRY-RUN]" in result.message
        assert "git clone" in result.message

    @pytest.mark.asyncio
    async def test_clone_success(
        self,
        deploy_worker: DeployWorker,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试成功克隆"""
        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="Directory created"),
            # test -d (不存在)
            WorkerResult(
                success=True,
                data={"stdout": "DIR_NOT_EXISTS"},
                message="Check complete",
            ),
            # git clone
            WorkerResult(success=True, message="Cloned successfully"),
        ]

        result = await deploy_worker.execute(
            "clone_repo",
            {
                "repo_url": "https://github.com/owner/test-repo",
                "target_dir": "/tmp/test",
            },
        )

        assert result.success
        assert "Successfully cloned" in result.message
        assert not result.task_completed

    @pytest.mark.asyncio
    async def test_clone_already_exists(
        self,
        deploy_worker: DeployWorker,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试仓库已存在"""
        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="Directory created"),
            # test -d (存在)
            WorkerResult(
                success=True,
                data={"stdout": "DIR_EXISTS"},
                message="Check complete",
            ),
        ]

        result = await deploy_worker.execute(
            "clone_repo",
            {
                "repo_url": "https://github.com/owner/test-repo",
                "target_dir": "/tmp/test",
            },
        )

        assert result.success
        assert "already exists" in result.message


class TestSetupEnv:
    """setup_env 动作测试"""

    @pytest.mark.asyncio
    async def test_missing_project_dir(self, deploy_worker: DeployWorker) -> None:
        """测试缺少 project_dir 参数"""
        result = await deploy_worker.execute("setup_env", {})
        assert not result.success
        assert "project_dir parameter is required" in result.message

    @pytest.mark.asyncio
    async def test_dry_run_setup(self, deploy_worker: DeployWorker) -> None:
        """测试 dry-run 模式"""
        result = await deploy_worker.execute(
            "setup_env",
            {
                "project_dir": "/tmp/test-repo",
                "project_type": "nodejs",
                "dry_run": True,
            },
        )

        assert result.success
        assert result.simulated
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_setup_with_env_example(
        self,
        deploy_worker: DeployWorker,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试有 .env.example 时的设置"""
        mock_shell_worker.execute.side_effect = [
            # 检查 .env.example
            WorkerResult(
                success=True,
                data={"stdout": "has_env_example"},
                message="Check complete",
            ),
            # 复制 .env
            WorkerResult(success=True, message="Copied"),
            # npm install
            WorkerResult(success=True, message="Installed"),
        ]

        result = await deploy_worker.execute(
            "setup_env",
            {
                "project_dir": "/tmp/test-repo",
                "project_type": "nodejs",
            },
        )

        assert result.success
        assert "Environment setup complete" in result.message


class TestStartService:
    """start_service 动作测试"""

    @pytest.mark.asyncio
    async def test_missing_project_dir(self, deploy_worker: DeployWorker) -> None:
        """测试缺少 project_dir 参数"""
        result = await deploy_worker.execute("start_service", {})
        assert not result.success
        assert "project_dir parameter is required" in result.message

    @pytest.mark.asyncio
    async def test_unknown_project_type(self, deploy_worker: DeployWorker) -> None:
        """测试未知项目类型"""
        result = await deploy_worker.execute(
            "start_service",
            {
                "project_dir": "/tmp/test",
                "project_type": "unknown",
            },
        )
        assert not result.success
        assert "No start command" in result.message

    @pytest.mark.asyncio
    async def test_dry_run_start(self, deploy_worker: DeployWorker) -> None:
        """测试 dry-run 模式"""
        result = await deploy_worker.execute(
            "start_service",
            {
                "project_dir": "/tmp/test-repo",
                "project_type": "docker",
                "dry_run": True,
            },
        )

        assert result.success
        assert result.simulated
        assert "[DRY-RUN]" in result.message
        assert "docker compose up" in result.message

    @pytest.mark.asyncio
    async def test_start_docker_service(
        self,
        deploy_worker: DeployWorker,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试启动 Docker 服务"""
        mock_shell_worker.execute.return_value = WorkerResult(
            success=True,
            message="Container started",
        )

        result = await deploy_worker.execute(
            "start_service",
            {
                "project_dir": "/tmp/test-repo",
                "project_type": "docker",
            },
        )

        assert result.success
        assert result.task_completed
        assert "started successfully" in result.message


class TestProjectTypeDetection:
    """项目类型检测测试"""

    def test_detect_docker_from_dockerfile(self, deploy_worker: DeployWorker) -> None:
        """测试从 Dockerfile 检测 Docker 项目"""
        project_type, matched = deploy_worker._detect_project_type(["Dockerfile"])
        assert project_type == "docker"
        assert "Dockerfile" in matched

    def test_detect_docker_from_compose(self, deploy_worker: DeployWorker) -> None:
        """测试从 docker-compose.yml 检测 Docker 项目"""
        project_type, matched = deploy_worker._detect_project_type(["docker-compose.yml"])
        assert project_type == "docker"

    def test_detect_nodejs(self, deploy_worker: DeployWorker) -> None:
        """测试检测 Node.js 项目"""
        project_type, matched = deploy_worker._detect_project_type(["package.json"])
        assert project_type == "nodejs"

    def test_detect_python_requirements(self, deploy_worker: DeployWorker) -> None:
        """测试从 requirements.txt 检测 Python 项目"""
        project_type, matched = deploy_worker._detect_project_type(["requirements.txt"])
        assert project_type == "python"

    def test_detect_python_pyproject(self, deploy_worker: DeployWorker) -> None:
        """测试从 pyproject.toml 检测 Python 项目"""
        project_type, matched = deploy_worker._detect_project_type(["pyproject.toml"])
        assert project_type == "python"

    def test_detect_go(self, deploy_worker: DeployWorker) -> None:
        """测试检测 Go 项目"""
        project_type, matched = deploy_worker._detect_project_type(["go.mod"])
        assert project_type == "go"

    def test_detect_rust(self, deploy_worker: DeployWorker) -> None:
        """测试检测 Rust 项目"""
        project_type, matched = deploy_worker._detect_project_type(["Cargo.toml"])
        assert project_type == "rust"

    def test_docker_priority(self, deploy_worker: DeployWorker) -> None:
        """测试 Docker 优先级高于其他类型"""
        project_type, matched = deploy_worker._detect_project_type(
            ["Dockerfile", "package.json", "requirements.txt"]
        )
        assert project_type == "docker"

    def test_unknown_type(self, deploy_worker: DeployWorker) -> None:
        """测试未知项目类型"""
        project_type, matched = deploy_worker._detect_project_type(["README.md", "LICENSE"])
        assert project_type == "unknown"
        assert matched == []


class TestOneClickDeploy:
    """测试一键部署功能"""

    @pytest.mark.asyncio
    async def test_one_click_deploy_success(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试一键部署成功流程"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker)

        # Mock analyze_repo (README)
        mock_http_worker.execute.side_effect = [
            # fetch_github_readme
            WorkerResult(
                success=True,
                data={"content": "# Test Project\n\nA test project."},
                message="README fetched",
            ),
            # list_github_files
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml, README.md"},
                message="Files listed",
            ),
        ]

        # Mock clone and setup - full flow for docker project
        # Docker: install = "docker compose up -d", start = "docker compose up -d"
        mock_shell_worker.execute.side_effect = [
            # mkdir (clone)
            WorkerResult(success=True, message="Directory created"),
            # check exists (clone)
            WorkerResult(success=True, data={"stdout": "DIR_NOT_EXISTS"}, message="Checked"),
            # git clone
            WorkerResult(success=True, message="Cloned"),
            # check env example (setup_env)
            WorkerResult(success=True, data={"stdout": "no_env_example"}, message="No env"),
            # docker compose up -d (install in setup_env)
            WorkerResult(success=True, message="Dependencies installed"),
            # docker compose up -d (start_service)
            WorkerResult(success=True, message="Started"),
        ]

        result = await deploy_worker.execute(
            "deploy",
            {
                "repo_url": "https://github.com/test/repo",
            },
        )

        assert result.success is True
        assert "✅ 部署完成" in result.message
        assert result.task_completed is True

    @pytest.mark.asyncio
    async def test_one_click_deploy_dry_run(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试一键部署 dry-run 模式"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker)

        # Mock analyze_repo
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Test"},
                message="README",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml"},
                message="Files",
            ),
        ]

        # Mock dry-run responses - need mkdir for clone step
        mock_shell_worker.execute.return_value = WorkerResult(
            success=True,
            message="[DRY-RUN]",
            data={"stdout": "DIR_NOT_EXISTS"},
            simulated=True,
        )

        result = await deploy_worker.execute(
            "deploy",
            {
                "repo_url": "https://github.com/test/repo",
                "dry_run": True,
            },
        )

        assert result.success is True
        assert "[DRY-RUN 模式]" in result.message
        assert result.simulated is True

    @pytest.mark.asyncio
    async def test_one_click_deploy_missing_url(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试缺少 repo_url 参数"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker)

        result = await deploy_worker.execute("deploy", {})

        assert result.success is False
        assert "repo_url" in result.message

    @pytest.mark.asyncio
    async def test_one_click_deploy_with_start_error(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
    ) -> None:
        """测试启动服务失败时的建议"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker)

        # Mock analyze_repo
        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Test"}, message="README"),
            WorkerResult(success=True, data={"key_files": "docker-compose.yml"}, message="Files"),
        ]

        # Mock shell - fail at start_service with port error
        # Docker: install = "docker compose up -d", start = "docker compose up -d"
        mock_shell_worker.execute.side_effect = [
            WorkerResult(success=True, message="mkdir"),
            WorkerResult(success=True, data={"stdout": "DIR_NOT_EXISTS"}, message="Check"),
            WorkerResult(success=True, message="Clone"),
            WorkerResult(success=True, data={"stdout": "no_env_example"}, message="No env"),
            # install command in setup_env succeeds
            WorkerResult(success=True, message="Dependencies installed"),
            # start_service fails with port error
            WorkerResult(success=False, message="Error: address already in use: 8080"),
        ]

        result = await deploy_worker.execute(
            "deploy",
            {
                "repo_url": "https://github.com/test/repo",
            },
        )

        assert result.success is False
        assert "可能的解决方法" in result.message
        assert "检查端口占用" in result.message
