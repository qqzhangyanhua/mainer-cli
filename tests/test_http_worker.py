"""HttpWorker 单元测试"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.config.manager import HttpConfig
from src.workers.http import HttpWorker


@pytest.fixture
def http_worker() -> HttpWorker:
    """创建 HttpWorker 实例"""
    config = HttpConfig(timeout=10)
    return HttpWorker(config)


class TestParseGithubUrl:
    """测试 GitHub URL 解析"""

    def test_parse_standard_url(self, http_worker: HttpWorker) -> None:
        """测试标准 URL"""
        result = http_worker._parse_github_url("https://github.com/user/repo")
        assert result == ("user", "repo")

    def test_parse_url_with_trailing_slash(self, http_worker: HttpWorker) -> None:
        """测试带尾部斜杠的 URL"""
        result = http_worker._parse_github_url("https://github.com/user/repo/")
        assert result == ("user", "repo")

    def test_parse_url_with_git_suffix(self, http_worker: HttpWorker) -> None:
        """测试 .git 后缀"""
        result = http_worker._parse_github_url("https://github.com/user/repo.git")
        assert result == ("user", "repo")

    def test_parse_url_with_dashes(self, http_worker: HttpWorker) -> None:
        """测试带短横线的名称"""
        result = http_worker._parse_github_url("https://github.com/user-name/repo-name")
        assert result == ("user-name", "repo-name")

    def test_parse_invalid_url(self, http_worker: HttpWorker) -> None:
        """测试无效 URL"""
        result = http_worker._parse_github_url("https://gitlab.com/user/repo")
        assert result is None


class TestFetchUrl:
    """测试 fetch_url action"""

    @pytest.mark.asyncio
    async def test_fetch_url_success(self, http_worker: HttpWorker) -> None:
        """测试成功获取 URL 内容"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "Hello, World!"
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await http_worker.execute("fetch_url", {"url": "https://example.com"})

        assert result.success is True
        assert "Hello, World!" in result.message

    @pytest.mark.asyncio
    async def test_fetch_url_invalid_url(self, http_worker: HttpWorker) -> None:
        """测试无效 URL"""
        result = await http_worker.execute("fetch_url", {"url": "not-a-valid-url"})

        assert result.success is False
        assert "Invalid URL" in result.message

    @pytest.mark.asyncio
    async def test_fetch_url_missing_url(self, http_worker: HttpWorker) -> None:
        """测试缺少 URL 参数"""
        result = await http_worker.execute("fetch_url", {})

        assert result.success is False
        assert "url" in result.message.lower()


class TestFetchGithubReadme:
    """测试 fetch_github_readme action"""

    @pytest.mark.asyncio
    async def test_fetch_readme_success(self, http_worker: HttpWorker) -> None:
        """测试成功获取 README"""

        async def mock_get(url: str, headers: Optional[dict[str, str]] = None) -> AsyncMock:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "# Project Title\n\nThis is a README."
            return mock_response

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await http_worker.execute(
                "fetch_github_readme", {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "Project Title" in result.message

    @pytest.mark.asyncio
    async def test_fetch_readme_invalid_url(self, http_worker: HttpWorker) -> None:
        """测试非 GitHub URL"""
        result = await http_worker.execute(
            "fetch_github_readme", {"repo_url": "https://gitlab.com/user/repo"}
        )

        assert result.success is False
        assert "Invalid GitHub URL" in result.message


class TestListGithubFiles:
    """测试 list_github_files action"""

    @pytest.mark.asyncio
    async def test_list_files_success(self, http_worker: HttpWorker) -> None:
        """测试成功列出文件"""

        async def mock_get(url: str, headers: Optional[dict[str, str]] = None) -> AsyncMock:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_response.json = lambda: [
                {"name": "README.md", "type": "file", "path": "README.md", "size": 1024},
                {"name": "Dockerfile", "type": "file", "path": "Dockerfile", "size": 512},
                {"name": "src", "type": "dir", "path": "src", "size": 0},
            ]
            return mock_response

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await http_worker.execute(
                "list_github_files", {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_list_files_detects_dockerfile(self, http_worker: HttpWorker) -> None:
        """测试检测 Dockerfile 存在"""

        async def mock_get(url: str, headers: Optional[dict[str, str]] = None) -> AsyncMock:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_response.json = lambda: [
                {"name": "Dockerfile", "type": "file", "path": "Dockerfile", "size": 512},
                {
                    "name": "docker-compose.yml",
                    "type": "file",
                    "path": "docker-compose.yml",
                    "size": 256,
                },
            ]
            return mock_response

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await http_worker.execute(
                "list_github_files", {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "Dockerfile" in result.message


class TestUnknownAction:
    """测试未知 action"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, http_worker: HttpWorker) -> None:
        """测试未知 action 返回错误"""
        result = await http_worker.execute("unknown_action", {})

        assert result.success is False
        assert "Unknown action" in result.message
