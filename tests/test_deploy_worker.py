"""DeployWorker 单元测试

测试 LLM 驱动的智能部署 Worker。
DeployWorker 只暴露一个 action: deploy（一键部署）。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
def mock_llm_client() -> MagicMock:
    """创建模拟的 LLMClient"""
    client = MagicMock()
    client.generate = AsyncMock(return_value='{"steps": []}')
    client.parse_json_response = MagicMock(return_value={"steps": []})
    return client


@pytest.fixture
def deploy_worker(
    mock_http_worker: MagicMock,
    mock_shell_worker: MagicMock,
    mock_llm_client: MagicMock,
) -> DeployWorker:
    """创建 DeployWorker 实例"""
    return DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)


class TestDeployWorkerBasic:
    """基本属性测试"""

    def test_name(self, deploy_worker: DeployWorker) -> None:
        """测试 Worker 名称"""
        assert deploy_worker.name == "deploy"

    def test_capabilities(self, deploy_worker: DeployWorker) -> None:
        """测试 Worker 能力列表 - 只暴露一键部署"""
        caps = deploy_worker.get_capabilities()
        assert caps == ["deploy"]

    @pytest.mark.asyncio
    async def test_unknown_action(self, deploy_worker: DeployWorker) -> None:
        """测试未知动作"""
        result = await deploy_worker.execute("unknown_action", {})
        assert not result.success
        assert "Unknown action" in result.message


class TestGitHubUrlParsing:
    """GitHub URL 解析测试"""

    def test_valid_url(self, deploy_worker: DeployWorker) -> None:
        parsed = deploy_worker._parse_github_url("https://github.com/owner/repo")
        assert parsed == ("owner", "repo")

    def test_valid_url_with_git_suffix(self, deploy_worker: DeployWorker) -> None:
        parsed = deploy_worker._parse_github_url("https://github.com/owner/repo.git")
        assert parsed == ("owner", "repo")

    def test_valid_url_with_trailing_slash(self, deploy_worker: DeployWorker) -> None:
        parsed = deploy_worker._parse_github_url("https://github.com/owner/repo/")
        assert parsed == ("owner", "repo")

    def test_invalid_url(self, deploy_worker: DeployWorker) -> None:
        parsed = deploy_worker._parse_github_url("https://example.com/not-github")
        assert parsed is None

    def test_empty_url(self, deploy_worker: DeployWorker) -> None:
        parsed = deploy_worker._parse_github_url("")
        assert parsed is None


class TestDeployMissingParams:
    """deploy action 参数校验测试"""

    @pytest.mark.asyncio
    async def test_missing_repo_url(self, deploy_worker: DeployWorker) -> None:
        """测试缺少 repo_url 参数"""
        result = await deploy_worker.execute("deploy", {})
        assert not result.success
        assert "repo_url" in result.message

    @pytest.mark.asyncio
    async def test_invalid_github_url(self, deploy_worker: DeployWorker) -> None:
        """测试无效的 GitHub URL"""
        result = await deploy_worker.execute(
            "deploy", {"repo_url": "https://example.com/not-github"}
        )
        assert not result.success
        assert "无效" in result.message or "URL" in result.message


class TestDeployDryRun:
    """deploy dry-run 模式测试"""

    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试 dry-run 模式返回模拟结果"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        # Mock HTTP: README + 文件列表
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

        # LLM 返回部署计划
        plan_response = {
            "thinking": ["Docker 项目"],
            "project_type": "docker",
            "steps": [
                {"description": "构建镜像", "command": "docker build -t app ."},
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        # Shell: dry-run 不需要真正执行，但 planner.collect_env_info 会调用
        mock_shell_worker.execute.return_value = WorkerResult(
            success=True,
            message="ok",
            data={"stdout": ""},
        )

        result = await deploy_worker.execute(
            "deploy",
            {"repo_url": "https://github.com/test/repo", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN" in result.message


class TestDeploySuccess:
    """deploy 成功流程测试"""

    @pytest.mark.asyncio
    async def test_deploy_success_with_llm_plan(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试一键部署成功流程（LLM 生成计划）"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        # Mock HTTP: README + 文件列表
        mock_http_worker.execute.side_effect = [
            WorkerResult(
                success=True,
                data={"content": "# Test Project"},
                message="README fetched",
            ),
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml, README.md"},
                message="Files listed",
            ),
        ]

        # LLM 返回部署计划
        plan_response = {
            "thinking": ["这是一个 Docker 项目"],
            "project_type": "docker",
            "steps": [
                {
                    "description": "启动服务",
                    "command": "docker compose up -d",
                    "risk_level": "safe",
                },
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        # Shell 调用序列:
        # 1-5: collect_env_info (python, docker, docker info, node, uv)
        # 6: collect_key_file_contents (read_local_file) - 通过 patch
        # 7: mkdir
        # 8: check exists
        # 9: git clone
        # 10: execute step (docker compose up -d)
        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="Directory created"),
            # check exists
            WorkerResult(
                success=True,
                data={"stdout": "NOT_EXISTS"},
                message="Checked",
            ),
            # git clone
            WorkerResult(success=True, message="Cloned"),
            # collect_env_info: python, docker, docker info, node, uv
            env_result,
            env_result,
            env_result,
            env_result,
            env_result,
            # execute step: docker compose up -d
            WorkerResult(success=True, message="Started"),
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/repo"},
            )

        assert result.success is True
        assert "部署完成" in result.message
        assert result.task_completed is True


class TestDeployFailure:
    """deploy 失败场景测试"""

    @pytest.mark.asyncio
    async def test_clone_failure(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试克隆失败"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Test"}, message="README"),
            WorkerResult(
                success=True, data={"key_files": "Dockerfile"}, message="Files"
            ),
        ]

        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="ok"),
            # check exists
            WorkerResult(
                success=True, data={"stdout": "NOT_EXISTS"}, message="Checked"
            ),
            # git clone fails
            WorkerResult(success=False, message="fatal: repository not found"),
        ]

        result = await deploy_worker.execute(
            "deploy",
            {"repo_url": "https://github.com/test/nonexistent"},
        )

        assert result.success is False
        assert "克隆失败" in result.message

    @pytest.mark.asyncio
    async def test_empty_plan_from_llm(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试 LLM 返回空部署计划"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Test"}, message="README"),
            WorkerResult(
                success=True, data={"key_files": "README.md"}, message="Files"
            ),
        ]

        # LLM 返回空计划
        mock_llm_client.parse_json_response.return_value = {
            "steps": [],
            "project_type": "unknown",
            "notes": "",
        }

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="ok"),
            # check exists
            WorkerResult(
                success=True, data={"stdout": "NOT_EXISTS"}, message="Checked"
            ),
            # git clone
            WorkerResult(success=True, message="Cloned"),
            # collect_env_info: 5 calls
            env_result, env_result, env_result, env_result, env_result,
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/repo"},
            )

        assert result.success is False
        assert "无法生成部署计划" in result.message


class TestDeployStepFailure:
    """deploy 步骤执行失败测试"""

    @pytest.mark.asyncio
    async def test_step_execution_failure(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试部署步骤执行失败时的错误信息"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Test"}, message="README"),
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml"},
                message="Files",
            ),
        ]

        plan_response = {
            "thinking": ["Docker 项目"],
            "project_type": "docker",
            "steps": [
                {
                    "description": "启动服务",
                    "command": "docker compose up -d",
                    "risk_level": "safe",
                },
            ],
            "notes": "",
        }

        diagnose_response = {
            "thinking": ["无法修复"],
            "action": "give_up",
            "cause": "未知配置错误",
            "suggestion": "手动检查项目",
        }

        # 用一个函数根据调用顺序返回不同结果
        generate_call_count = 0

        async def mock_generate(*args: object, **kwargs: object) -> str:
            nonlocal generate_call_count
            generate_call_count += 1
            if generate_call_count == 1:
                return json.dumps(plan_response)
            return json.dumps(diagnose_response)

        mock_llm_client.generate = AsyncMock(side_effect=mock_generate)

        parse_call_count = 0
        original_parse = mock_llm_client.parse_json_response

        def mock_parse(response: str) -> dict[str, object]:
            nonlocal parse_call_count
            parse_call_count += 1
            if parse_call_count == 1:
                return plan_response
            return diagnose_response

        mock_llm_client.parse_json_response = MagicMock(side_effect=mock_parse)

        # 用一个函数根据调用顺序返回不同 shell 结果
        shell_call_count = 0

        async def mock_shell_execute(action: str, args: dict[str, object]) -> WorkerResult:
            nonlocal shell_call_count
            shell_call_count += 1
            cmd = args.get("command", "")
            # 前 3 次：mkdir, check exists, git clone
            if shell_call_count <= 3:
                if shell_call_count == 2:
                    return WorkerResult(
                        success=True, data={"stdout": "NOT_EXISTS"}, message="Checked"
                    )
                return WorkerResult(success=True, message="ok", data={"stdout": ""})
            # collect_env_info 阶段：返回空 stdout 的成功结果
            if isinstance(cmd, str) and any(
                kw in cmd for kw in ["version", "docker info", "--version"]
            ):
                return WorkerResult(success=True, message="ok", data={"stdout": ""})
            # execute_with_retry 阶段的命令：失败
            if isinstance(cmd, str) and "docker compose" in cmd:
                return WorkerResult(
                    success=False, message="Error: unknown configuration error"
                )
            # 其他命令默认成功
            return WorkerResult(success=True, message="ok", data={"stdout": ""})

        mock_shell_worker.execute = AsyncMock(side_effect=mock_shell_execute)

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/repo"},
            )

        assert result.success is False
        assert "可能的解决方法" in result.message


class TestDeployCallbacks:
    """回调设置测试"""

    def test_set_progress_callback(self, deploy_worker: DeployWorker) -> None:
        """测试设置进度回调"""
        callback = MagicMock()
        deploy_worker.set_progress_callback(callback)
        assert deploy_worker._progress_callback is callback

    def test_set_confirmation_callback(self, deploy_worker: DeployWorker) -> None:
        """测试设置确认回调"""
        callback = AsyncMock()
        deploy_worker.set_confirmation_callback(callback)
        assert deploy_worker._confirmation_callback is callback

    def test_set_ask_user_callback(self, deploy_worker: DeployWorker) -> None:
        """测试设置用户选择回调"""
        callback = AsyncMock()
        deploy_worker.set_ask_user_callback(callback)
        assert deploy_worker._ask_user_callback is callback


class TestDeployAlreadyCloned:
    """项目已存在场景测试"""

    @pytest.mark.asyncio
    async def test_repo_already_exists_skips_clone(
        self,
        mock_http_worker: MagicMock,
        mock_shell_worker: MagicMock,
        mock_llm_client: MagicMock,
    ) -> None:
        """测试项目已存在时跳过克隆"""
        deploy_worker = DeployWorker(mock_http_worker, mock_shell_worker, mock_llm_client)

        mock_http_worker.execute.side_effect = [
            WorkerResult(success=True, data={"content": "# Test"}, message="README"),
            WorkerResult(
                success=True,
                data={"key_files": "docker-compose.yml"},
                message="Files",
            ),
        ]

        plan_response = {
            "thinking": ["已存在"],
            "project_type": "docker",
            "steps": [
                {"description": "启动", "command": "docker compose up -d"},
            ],
            "notes": "",
        }
        mock_llm_client.generate.return_value = json.dumps(plan_response)
        mock_llm_client.parse_json_response.return_value = plan_response

        env_result = WorkerResult(success=True, message="ok", data={"stdout": ""})
        mock_shell_worker.execute.side_effect = [
            # mkdir
            WorkerResult(success=True, message="ok"),
            # check exists - 返回 EXISTS（项目已存在）
            WorkerResult(
                success=True,
                data={"stdout": "EXISTS"},
                message="Checked",
            ),
            # collect_env_info: 5 calls
            env_result, env_result, env_result, env_result, env_result,
            # execute step
            WorkerResult(success=True, message="Started"),
        ]

        with patch("os.path.exists", return_value=False):
            result = await deploy_worker.execute(
                "deploy",
                {"repo_url": "https://github.com/test/repo"},
            )

        assert result.success is True
        assert "已存在" in result.message
        # 验证没有调用 git clone（check exists 后直接到 env_info）
        calls = mock_shell_worker.execute.call_args_list
        commands = [
            str(c.args[1].get("command", "") if len(c.args) > 1 else c.kwargs.get("command", ""))
            for c in calls
        ]
        assert not any("git clone" in cmd for cmd in commands)
