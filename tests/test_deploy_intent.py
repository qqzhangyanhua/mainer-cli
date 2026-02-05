"""部署意图识别测试"""

from __future__ import annotations

from typing import Optional

import pytest

from src.orchestrator.preprocessor import RequestPreprocessor


class TestDeployIntentDetection:
    """测试 deploy 意图检测"""

    @pytest.fixture
    def preprocessor(self) -> RequestPreprocessor:
        return RequestPreprocessor()

    @pytest.mark.parametrize(
        "input_text,expected_intent",
        [
            # deploy 意图
            ("帮我部署 https://github.com/user/repo", "deploy"),
            ("https://github.com/user/repo 这个项目怎么跑起来", "deploy"),
            ("deploy https://github.com/user/repo", "deploy"),
            ("安装 https://github.com/user/repo", "deploy"),
            ("启动 https://github.com/user/repo 这个项目", "deploy"),
            ("运行 https://github.com/user/repo", "deploy"),
            # 非 deploy 意图（有 URL 但无部署关键词）
            ("https://github.com/user/repo 这是什么项目", "explain"),
            # 其他意图
            ("你好", "greeting"),
            ("检查磁盘使用情况", "unknown"),
            ("我有哪些 docker 服务", "list"),
        ],
    )
    def test_detect_intent(
        self,
        preprocessor: RequestPreprocessor,
        input_text: str,
        expected_intent: str,
    ) -> None:
        """测试意图检测"""
        result = preprocessor.preprocess(input_text)
        assert result.intent == expected_intent, f"Input: {input_text}"


class TestExtractRepoUrl:
    """测试仓库 URL 提取"""

    @pytest.fixture
    def preprocessor(self) -> RequestPreprocessor:
        return RequestPreprocessor()

    @pytest.mark.parametrize(
        "input_text,expected_url",
        [
            (
                "帮我部署 https://github.com/user/repo",
                "https://github.com/user/repo",
            ),
            (
                "https://github.com/user/my-repo 这个项目",
                "https://github.com/user/my-repo",
            ),
            (
                "部署 https://gitlab.com/user/repo",
                "https://gitlab.com/user/repo",
            ),
            ("没有 URL 的文本", None),
        ],
    )
    def test_extract_repo_url(
        self,
        preprocessor: RequestPreprocessor,
        input_text: str,
        expected_url: Optional[str],
    ) -> None:
        """测试 URL 提取"""
        result = preprocessor.extract_repo_url(input_text)
        assert result == expected_url


class TestDeployIntentWithGitLab:
    """测试 GitLab URL 的部署意图"""

    @pytest.fixture
    def preprocessor(self) -> RequestPreprocessor:
        return RequestPreprocessor()

    def test_gitlab_deploy_intent(self, preprocessor: RequestPreprocessor) -> None:
        """测试 GitLab URL 也能触发部署意图"""
        result = preprocessor.preprocess("部署 https://gitlab.com/user/repo")
        assert result.intent == "deploy"

    def test_gitlab_url_extraction(self, preprocessor: RequestPreprocessor) -> None:
        """测试 GitLab URL 提取"""
        url = preprocessor.extract_repo_url("https://gitlab.com/org/project")
        assert url == "https://gitlab.com/org/project"
