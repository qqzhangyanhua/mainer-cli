"""部署功能端到端集成测试"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.config.manager import OpsAIConfig
from src.orchestrator.engine import OrchestratorEngine


class TestDeployIntegration:
    """部署功能集成测试"""

    @pytest.fixture
    def config(self) -> OpsAIConfig:
        """创建测试配置"""
        return OpsAIConfig()

    @pytest.fixture
    def engine(self, config: OpsAIConfig) -> OrchestratorEngine:
        """创建引擎实例"""
        return OrchestratorEngine(config)

    def test_http_worker_registered(self, engine: OrchestratorEngine) -> None:
        """测试 HttpWorker 已注册"""
        worker = engine.get_worker("http")
        assert worker is not None
        assert worker.name == "http"

    def test_http_worker_capabilities(self, engine: OrchestratorEngine) -> None:
        """测试 HttpWorker 能力"""
        worker = engine.get_worker("http")
        assert worker is not None
        caps = worker.get_capabilities()
        assert "fetch_url" in caps
        assert "fetch_github_readme" in caps
        assert "list_github_files" in caps

    def test_deploy_intent_detected(self, engine: OrchestratorEngine) -> None:
        """测试部署意图被正确检测"""
        preprocessor = engine._preprocessor
        result = preprocessor.preprocess("帮我部署 https://github.com/user/repo")
        assert result.intent == "deploy"

    def test_deploy_intent_with_gitlab(self, engine: OrchestratorEngine) -> None:
        """测试 GitLab URL 也能触发部署意图"""
        preprocessor = engine._preprocessor
        result = preprocessor.preprocess("部署 https://gitlab.com/user/repo")
        assert result.intent == "deploy"

    def test_extract_repo_url(self, engine: OrchestratorEngine) -> None:
        """测试 URL 提取"""
        preprocessor = engine._preprocessor
        url = preprocessor.extract_repo_url("帮我部署 https://github.com/user/my-project")
        assert url == "https://github.com/user/my-project"

    @pytest.mark.asyncio
    async def test_http_worker_fetch_readme(self, engine: OrchestratorEngine) -> None:
        """测试 HttpWorker 获取 README"""
        http_worker = engine.get_worker("http")
        assert http_worker is not None

        # Mock HTTP 响应
        async def mock_get(url: str, headers: Optional[dict[str, str]] = None) -> AsyncMock:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "# Test Project\n\nThis is a test."
            return mock_response

        import httpx

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await http_worker.execute(
                "fetch_github_readme", {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "Test Project" in result.message


class TestDeployPromptSelection:
    """测试部署 Prompt 选择"""

    @pytest.fixture
    def config(self) -> OpsAIConfig:
        return OpsAIConfig()

    def test_deploy_prompt_contains_http_actions(self, config: OpsAIConfig) -> None:
        """测试部署 Prompt 包含 HTTP 操作"""
        engine = OrchestratorEngine(config)
        prompt_builder = engine._prompt_builder

        prompt = prompt_builder.build_deploy_prompt(
            engine._context,
            repo_url="https://github.com/user/repo",
            target_dir="~/projects",
        )

        assert "fetch_github_readme" in prompt
        assert "list_github_files" in prompt
        assert "git clone" in prompt.lower()

    def test_deploy_prompt_includes_repo_url(self, config: OpsAIConfig) -> None:
        """测试部署 Prompt 包含仓库 URL"""
        engine = OrchestratorEngine(config)
        prompt_builder = engine._prompt_builder

        repo_url = "https://github.com/test-user/test-repo"
        prompt = prompt_builder.build_deploy_prompt(
            engine._context,
            repo_url=repo_url,
            target_dir="~/projects",
        )

        assert repo_url in prompt


class TestWorkerCapabilities:
    """测试 Worker 能力在 Prompt 中的注册"""

    @pytest.fixture
    def config(self) -> OpsAIConfig:
        return OpsAIConfig()

    def test_prompt_includes_http_capabilities(self, config: OpsAIConfig) -> None:
        """测试 Prompt 包含 HTTP 能力"""
        engine = OrchestratorEngine(config)
        caps = engine._prompt_builder.get_worker_capabilities()

        assert "http" in caps
        assert "fetch_github_readme" in caps
        assert "list_github_files" in caps
