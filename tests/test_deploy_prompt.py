"""部署 Prompt 测试"""

from __future__ import annotations

import pytest

from src.context.environment import EnvironmentContext
from src.orchestrator.prompt import PromptBuilder


class TestDeployPrompt:
    """测试部署 Prompt"""

    @pytest.fixture
    def prompt_builder(self) -> PromptBuilder:
        return PromptBuilder()

    @pytest.fixture
    def context(self) -> EnvironmentContext:
        return EnvironmentContext()

    def test_deploy_prompt_contains_http_worker(
        self,
        prompt_builder: PromptBuilder,
        context: EnvironmentContext,
    ) -> None:
        """测试部署 Prompt 包含 http worker"""
        prompt = prompt_builder.build_deploy_prompt(
            context,
            repo_url="https://github.com/user/repo",
            target_dir="~/projects",
        )

        assert "http" in prompt
        assert "fetch_github_readme" in prompt
        assert "list_github_files" in prompt

    def test_deploy_prompt_contains_deployment_guidance(
        self,
        prompt_builder: PromptBuilder,
        context: EnvironmentContext,
    ) -> None:
        """测试部署 Prompt 包含部署原则"""
        prompt = prompt_builder.build_deploy_prompt(
            context,
            repo_url="https://github.com/user/repo",
            target_dir="~/projects",
        )

        assert "Dockerfile" in prompt
        assert "docker" in prompt.lower()

    def test_deploy_prompt_includes_repo_url(
        self,
        prompt_builder: PromptBuilder,
        context: EnvironmentContext,
    ) -> None:
        """测试部署 Prompt 包含仓库 URL"""
        repo_url = "https://github.com/user/test-repo"
        prompt = prompt_builder.build_deploy_prompt(
            context,
            repo_url=repo_url,
            target_dir="~/projects",
        )

        assert repo_url in prompt

    def test_deploy_prompt_includes_target_dir(
        self,
        prompt_builder: PromptBuilder,
        context: EnvironmentContext,
    ) -> None:
        """测试部署 Prompt 包含目标目录"""
        target_dir = "/opt/apps"
        prompt = prompt_builder.build_deploy_prompt(
            context,
            repo_url="https://github.com/user/repo",
            target_dir=target_dir,
        )

        assert target_dir in prompt

    def test_worker_capabilities_includes_http(
        self,
        prompt_builder: PromptBuilder,
    ) -> None:
        """测试 Worker 能力包含 http"""
        caps = prompt_builder.get_worker_capabilities()
        assert "http" in caps
        assert "fetch_github_readme" in caps
