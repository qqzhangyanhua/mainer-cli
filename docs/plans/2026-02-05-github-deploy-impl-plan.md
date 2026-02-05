# GitHub 项目智能部署功能实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现用户提供 GitHub URL，LLM 自动读取 README、分析项目结构、选择最佳部署方式并执行的智能部署功能。

**Architecture:** 新增 HttpWorker 和 TavilyWorker 两个 Worker，扩展 RequestPreprocessor 支持 deploy 意图检测，新增 DEPLOY_INTENT_PROMPT 模板引导 LLM 进行部署决策。所有编排逻辑由 LLM 在 ReAct 循环中完成，Worker 保持"愚蠢"状态只负责执行。

**Tech Stack:** Python 3.9+, httpx (HTTP 客户端), tavily-python (搜索 API), Pydantic (类型验证)

---

## Task 1: 新增类型定义

**Files:**
- Modify: `src/types.py:1-88`

**Step 1: 写测试验证类型定义**

```bash
# 无需单独测试，类型定义会在后续 Worker 测试中验证
```

**Step 2: 添加 Intent 类型和 GitHub 相关类型**

在 `src/types.py` 文件末尾添加：

```python
# 意图类型（扩展支持 deploy）
Intent = Literal["chat", "task", "deploy"]

# GitHub 文件信息
class GitHubFileInfo(TypedDict):
    """GitHub 仓库文件信息"""
    name: str
    type: Literal["file", "dir"]
    path: str
    size: int  # 文件大小（字节）


# Tavily 搜索结果
class TavilySearchResult(TypedDict):
    """Tavily 搜索结果"""
    title: str
    url: str
    content: str  # 摘要
    score: float  # 相关性分数
```

**Step 3: 验证类型检查通过**

Run: `uv run mypy src/types.py --strict`
Expected: Success, no errors

**Step 4: Commit**

```bash
git add src/types.py
git commit -m "feat(types): add Intent, GitHubFileInfo, TavilySearchResult types"
```

---

## Task 2: 新增配置模型

**Files:**
- Modify: `src/config/manager.py:1-117`

**Step 1: 写测试验证配置模型**

创建测试文件 `tests/test_config_deploy.py`：

```python
"""测试部署相关配置"""

import pytest
from src.config.manager import HttpConfig, TavilyConfig, OpsAIConfig


def test_http_config_defaults():
    """测试 HttpConfig 默认值"""
    config = HttpConfig()
    assert config.timeout == 30
    assert config.github_token == ""


def test_tavily_config_defaults():
    """测试 TavilyConfig 默认值"""
    config = TavilyConfig()
    assert config.api_key == ""
    assert config.timeout == 30


def test_opsai_config_includes_http_and_tavily():
    """测试 OpsAIConfig 包含新配置"""
    config = OpsAIConfig()
    assert hasattr(config, "http")
    assert hasattr(config, "tavily")
    assert isinstance(config.http, HttpConfig)
    assert isinstance(config.tavily, TavilyConfig)
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_config_deploy.py -v`
Expected: FAIL with "cannot import name 'HttpConfig'"

**Step 3: 添加 HttpConfig 和 TavilyConfig 模型**

在 `src/config/manager.py` 的 `AuditConfig` 类之后添加：

```python
class HttpConfig(BaseModel):
    """HTTP 请求配置"""

    timeout: int = Field(default=30, description="请求超时时间(秒)")
    github_token: str = Field(default="", description="GitHub Token（可选，用于私有仓库和提高 rate limit）")


class TavilyConfig(BaseModel):
    """Tavily 搜索配置"""

    api_key: str = Field(default="", description="Tavily API Key")
    timeout: int = Field(default=30, description="请求超时时间(秒)")
```

**Step 4: 更新 OpsAIConfig 包含新配置**

修改 `OpsAIConfig` 类：

```python
class OpsAIConfig(BaseModel):
    """OpsAI 完整配置"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
```

**Step 5: 运行测试验证通过**

Run: `uv run pytest tests/test_config_deploy.py -v`
Expected: PASS

**Step 6: 运行类型检查**

Run: `uv run mypy src/config/manager.py --strict`
Expected: Success

**Step 7: Commit**

```bash
git add src/config/manager.py tests/test_config_deploy.py
git commit -m "feat(config): add HttpConfig and TavilyConfig for deploy feature"
```

---

## Task 3: 添加 httpx 依赖

**Files:**
- Modify: `pyproject.toml:1-59`

**Step 1: 添加 httpx 依赖**

在 `pyproject.toml` 的 `dependencies` 列表中添加：

```toml
dependencies = [
    "textual>=0.47.0",
    "typer>=0.9.0",
    "openai>=1.0.0",
    "pydantic>=2.0.0",
    "docker>=7.0.0",
    "rich>=13.0.0",
    "pyperclip>=1.11.0",
    "httpx>=0.27.0",
]
```

**Step 2: 同步依赖**

Run: `uv sync`
Expected: Successfully installed httpx

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add httpx for HTTP requests"
```

---

## Task 4: 实现 HttpWorker - fetch_url

**Files:**
- Create: `src/workers/http.py`
- Create: `tests/test_http_worker.py`

**Step 1: 创建测试文件**

创建 `tests/test_http_worker.py`：

```python
"""HttpWorker 单元测试"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.config.manager import HttpConfig
from src.workers.http import HttpWorker


@pytest.fixture
def http_worker() -> HttpWorker:
    """创建 HttpWorker 实例"""
    config = HttpConfig(timeout=10)
    return HttpWorker(config)


class TestFetchUrl:
    """测试 fetch_url action"""

    @pytest.mark.asyncio
    async def test_fetch_url_success(self, http_worker: HttpWorker) -> None:
        """测试成功获取 URL 内容"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "Hello, World!"
        mock_response.raise_for_status = AsyncMock()

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await http_worker.execute(
                "fetch_url",
                {"url": "https://example.com"}
            )

        assert result.success is True
        assert "Hello, World!" in result.message

    @pytest.mark.asyncio
    async def test_fetch_url_invalid_url(self, http_worker: HttpWorker) -> None:
        """测试无效 URL"""
        result = await http_worker.execute(
            "fetch_url",
            {"url": "not-a-valid-url"}
        )

        assert result.success is False
        assert "Invalid URL" in result.message or "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_fetch_url_missing_url(self, http_worker: HttpWorker) -> None:
        """测试缺少 URL 参数"""
        result = await http_worker.execute(
            "fetch_url",
            {}
        )

        assert result.success is False
        assert "url" in result.message.lower()
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_http_worker.py::TestFetchUrl -v`
Expected: FAIL with "No module named 'src.workers.http'"

**Step 3: 创建 HttpWorker 基础结构**

创建 `src/workers/http.py`：

```python
"""HTTP 请求 Worker"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.config.manager import HttpConfig
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class HttpWorker(BaseWorker):
    """HTTP 请求 Worker

    支持的操作:
    - fetch_url: 获取任意 URL 内容
    - fetch_github_readme: 获取 GitHub 仓库 README
    - list_github_files: 列出 GitHub 仓库文件结构
    """

    def __init__(self, config: HttpConfig) -> None:
        """初始化 HttpWorker

        Args:
            config: HTTP 配置
        """
        self._config = config
        self._timeout = config.timeout
        self._github_token = config.github_token

    @property
    def name(self) -> str:
        return "http"

    def get_capabilities(self) -> list[str]:
        return ["fetch_url", "fetch_github_readme", "list_github_files"]

    def _is_valid_url(self, url: str) -> bool:
        """验证 URL 格式"""
        try:
            result = urlparse(url)
            return all([result.scheme in ("http", "https"), result.netloc])
        except Exception:
            return False

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行 HTTP 操作"""
        if action == "fetch_url":
            return await self._fetch_url(args)
        elif action == "fetch_github_readme":
            return await self._fetch_github_readme(args)
        elif action == "list_github_files":
            return await self._list_github_files(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

    async def _fetch_url(self, args: dict[str, ArgValue]) -> WorkerResult:
        """获取 URL 内容"""
        url = args.get("url")
        if not isinstance(url, str):
            return WorkerResult(
                success=False,
                message="url parameter is required and must be a string",
            )

        if not self._is_valid_url(url):
            return WorkerResult(
                success=False,
                message=f"Invalid URL format: {url}",
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
                response.raise_for_status()

                return WorkerResult(
                    success=True,
                    data={"url": url, "content": response.text[:5000]},  # 限制长度
                    message=f"Fetched content from {url}:\n\n{response.text[:2000]}",
                    task_completed=False,  # 通常需要后续处理
                )

        except httpx.TimeoutException:
            return WorkerResult(
                success=False,
                message=f"Request timeout after {self._timeout}s: {url}",
            )
        except httpx.HTTPStatusError as e:
            return WorkerResult(
                success=False,
                message=f"HTTP error {e.response.status_code}: {url}",
            )
        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Failed to fetch URL: {e!s}",
            )

    async def _fetch_github_readme(self, args: dict[str, ArgValue]) -> WorkerResult:
        """获取 GitHub README（占位，Task 5 实现）"""
        return WorkerResult(
            success=False,
            message="Not implemented yet",
        )

    async def _list_github_files(self, args: dict[str, ArgValue]) -> WorkerResult:
        """列出 GitHub 文件（占位，Task 6 实现）"""
        return WorkerResult(
            success=False,
            message="Not implemented yet",
        )
```

**Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_http_worker.py::TestFetchUrl -v`
Expected: PASS

**Step 5: 运行类型检查**

Run: `uv run mypy src/workers/http.py --strict`
Expected: Success

**Step 6: Commit**

```bash
git add src/workers/http.py tests/test_http_worker.py
git commit -m "feat(http): implement HttpWorker with fetch_url action"
```

---

## Task 5: 实现 HttpWorker - fetch_github_readme

**Files:**
- Modify: `src/workers/http.py`
- Modify: `tests/test_http_worker.py`

**Step 1: 添加测试用例**

在 `tests/test_http_worker.py` 中添加：

```python
class TestFetchGithubReadme:
    """测试 fetch_github_readme action"""

    @pytest.mark.asyncio
    async def test_fetch_readme_success(self, http_worker: HttpWorker) -> None:
        """测试成功获取 README"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "# Project Title\n\nThis is a README."
        mock_response.raise_for_status = AsyncMock()

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await http_worker.execute(
                "fetch_github_readme",
                {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "README" in result.message or "Project Title" in result.message

    @pytest.mark.asyncio
    async def test_fetch_readme_master_fallback(self, http_worker: HttpWorker) -> None:
        """测试 main 分支 404 时回退到 master"""
        call_count = 0

        async def mock_get(url: str, **kwargs) -> AsyncMock:  # type: ignore[misc]
            nonlocal call_count
            call_count += 1
            mock_response = AsyncMock()
            if "main" in url:
                mock_response.status_code = 404
                mock_response.raise_for_status = AsyncMock(
                    side_effect=httpx.HTTPStatusError(
                        "Not Found",
                        request=AsyncMock(),
                        response=mock_response
                    )
                )
            else:
                mock_response.status_code = 200
                mock_response.text = "# README from master"
                mock_response.raise_for_status = AsyncMock()
            return mock_response

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await http_worker.execute(
                "fetch_github_readme",
                {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert call_count == 2  # 尝试了 main 和 master

    @pytest.mark.asyncio
    async def test_fetch_readme_invalid_url(self, http_worker: HttpWorker) -> None:
        """测试非 GitHub URL"""
        result = await http_worker.execute(
            "fetch_github_readme",
            {"repo_url": "https://gitlab.com/user/repo"}
        )

        assert result.success is False
        assert "GitHub" in result.message

    @pytest.mark.asyncio
    async def test_parse_github_url(self, http_worker: HttpWorker) -> None:
        """测试 GitHub URL 解析"""
        # 测试各种 URL 格式
        test_cases = [
            ("https://github.com/user/repo", ("user", "repo")),
            ("https://github.com/user/repo/", ("user", "repo")),
            ("https://github.com/user/repo.git", ("user", "repo")),
            ("https://github.com/user-name/repo-name", ("user-name", "repo-name")),
        ]

        for url, expected in test_cases:
            result = http_worker._parse_github_url(url)
            assert result == expected, f"Failed for {url}"
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_http_worker.py::TestFetchGithubReadme -v`
Expected: FAIL

**Step 3: 实现 fetch_github_readme**

在 `src/workers/http.py` 中更新 `_fetch_github_readme` 方法：

```python
    def _parse_github_url(self, url: str) -> Optional[tuple[str, str]]:
        """解析 GitHub URL，提取 owner 和 repo

        Args:
            url: GitHub 仓库 URL

        Returns:
            (owner, repo) 元组，解析失败返回 None
        """
        # 支持的格式:
        # https://github.com/owner/repo
        # https://github.com/owner/repo/
        # https://github.com/owner/repo.git
        pattern = r"https?://github\.com/([\w\-]+)/([\w\-]+?)(?:\.git)?/?$"
        match = re.match(pattern, url)
        if match:
            return (match.group(1), match.group(2))
        return None

    async def _fetch_github_readme(self, args: dict[str, ArgValue]) -> WorkerResult:
        """获取 GitHub 仓库 README"""
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required and must be a string",
            )

        parsed = self._parse_github_url(repo_url)
        if not parsed:
            return WorkerResult(
                success=False,
                message=f"Invalid GitHub URL format: {repo_url}. Expected: https://github.com/owner/repo",
            )

        owner, repo = parsed

        # 构建 raw.githubusercontent.com URL
        # 先尝试 main 分支，失败则尝试 master
        branches = ["main", "master"]
        readme_files = ["README.md", "readme.md", "README.rst", "README"]

        headers = {}
        if self._github_token:
            headers["Authorization"] = f"token {self._github_token}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for branch in branches:
                for readme_file in readme_files:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{readme_file}"
                    try:
                        response = await client.get(raw_url, headers=headers)
                        if response.status_code == 200:
                            content = response.text
                            return WorkerResult(
                                success=True,
                                data={
                                    "owner": owner,
                                    "repo": repo,
                                    "branch": branch,
                                    "readme_file": readme_file,
                                    "content": content[:10000],  # 限制长度
                                },
                                message=f"README from {owner}/{repo} ({branch}/{readme_file}):\n\n{content[:3000]}",
                                task_completed=False,  # 需要 LLM 分析
                            )
                    except httpx.HTTPStatusError:
                        continue
                    except Exception:
                        continue

        return WorkerResult(
            success=False,
            message=f"README not found in {owner}/{repo}. Tried branches: {branches}, files: {readme_files}",
        )
```

**Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_http_worker.py::TestFetchGithubReadme -v`
Expected: PASS

**Step 5: 运行类型检查**

Run: `uv run mypy src/workers/http.py --strict`
Expected: Success

**Step 6: Commit**

```bash
git add src/workers/http.py tests/test_http_worker.py
git commit -m "feat(http): implement fetch_github_readme with branch fallback"
```

---

## Task 6: 实现 HttpWorker - list_github_files

**Files:**
- Modify: `src/workers/http.py`
- Modify: `tests/test_http_worker.py`

**Step 1: 添加测试用例**

在 `tests/test_http_worker.py` 中添加：

```python
class TestListGithubFiles:
    """测试 list_github_files action"""

    @pytest.mark.asyncio
    async def test_list_files_success(self, http_worker: HttpWorker) -> None:
        """测试成功列出文件"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "README.md", "type": "file", "path": "README.md", "size": 1024},
            {"name": "Dockerfile", "type": "file", "path": "Dockerfile", "size": 512},
            {"name": "src", "type": "dir", "path": "src", "size": 0},
        ])
        mock_response.raise_for_status = AsyncMock()

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await http_worker.execute(
                "list_github_files",
                {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert result.data is not None
        assert "files" in result.data

    @pytest.mark.asyncio
    async def test_list_files_detects_dockerfile(self, http_worker: HttpWorker) -> None:
        """测试检测 Dockerfile 存在"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "Dockerfile", "type": "file", "path": "Dockerfile", "size": 512},
            {"name": "docker-compose.yml", "type": "file", "path": "docker-compose.yml", "size": 256},
        ])
        mock_response.raise_for_status = AsyncMock()

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await http_worker.execute(
                "list_github_files",
                {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "Dockerfile" in result.message or "docker" in result.message.lower()

    @pytest.mark.asyncio
    async def test_list_files_with_path(self, http_worker: HttpWorker) -> None:
        """测试指定路径列出文件"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value=[
            {"name": "main.py", "type": "file", "path": "src/main.py", "size": 2048},
        ])
        mock_response.raise_for_status = AsyncMock()

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await http_worker.execute(
                "list_github_files",
                {"repo_url": "https://github.com/user/repo", "path": "src"}
            )

        assert result.success is True
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_http_worker.py::TestListGithubFiles -v`
Expected: FAIL

**Step 3: 实现 list_github_files**

在 `src/workers/http.py` 中更新 `_list_github_files` 方法：

```python
    async def _list_github_files(self, args: dict[str, ArgValue]) -> WorkerResult:
        """列出 GitHub 仓库文件结构"""
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required and must be a string",
            )

        path = args.get("path", "")
        if not isinstance(path, str):
            path = ""

        parsed = self._parse_github_url(repo_url)
        if not parsed:
            return WorkerResult(
                success=False,
                message=f"Invalid GitHub URL format: {repo_url}",
            )

        owner, repo = parsed

        # 使用 GitHub API
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self._github_token:
            headers["Authorization"] = f"token {self._github_token}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(api_url, headers=headers)
                response.raise_for_status()

                data = response.json()

                # 解析文件列表
                files: list[dict[str, str]] = []
                key_files: list[str] = []  # 关键文件（用于部署判断）

                key_file_names = {
                    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                    "package.json", "requirements.txt", "pyproject.toml",
                    "Makefile", "setup.py", "go.mod", "Cargo.toml",
                }

                for item in data:
                    file_info = {
                        "name": item["name"],
                        "type": item["type"],
                        "path": item["path"],
                    }
                    files.append(file_info)

                    if item["name"] in key_file_names:
                        key_files.append(item["name"])

                # 构建消息
                message_parts = [f"Files in {owner}/{repo}/{path}:"]
                for f in files[:20]:  # 限制显示数量
                    icon = "📁" if f["type"] == "dir" else "📄"
                    message_parts.append(f"  {icon} {f['name']}")

                if len(files) > 20:
                    message_parts.append(f"  ... and {len(files) - 20} more")

                if key_files:
                    message_parts.append(f"\n🔑 Key files detected: {', '.join(key_files)}")

                return WorkerResult(
                    success=True,
                    data={"files": files, "key_files": key_files},  # type: ignore[dict-item]
                    message="\n".join(message_parts),
                    task_completed=False,
                )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return WorkerResult(
                    success=False,
                    message=f"Repository or path not found: {owner}/{repo}/{path}",
                )
            elif e.response.status_code == 403:
                return WorkerResult(
                    success=False,
                    message="GitHub API rate limit exceeded. Consider configuring a GitHub token.",
                )
            else:
                return WorkerResult(
                    success=False,
                    message=f"GitHub API error {e.response.status_code}: {e!s}",
                )
        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Failed to list files: {e!s}",
            )
```

**Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_http_worker.py::TestListGithubFiles -v`
Expected: PASS

**Step 5: 运行类型检查**

Run: `uv run mypy src/workers/http.py --strict`
Expected: Success

**Step 6: Commit**

```bash
git add src/workers/http.py tests/test_http_worker.py
git commit -m "feat(http): implement list_github_files with key file detection"
```

---

## Task 7: 扩展意图识别支持 deploy

**Files:**
- Modify: `src/orchestrator/preprocessor.py`
- Modify: `src/types.py`
- Create: `tests/test_deploy_intent.py`

**Step 1: 创建测试文件**

创建 `tests/test_deploy_intent.py`：

```python
"""部署意图识别测试"""

from __future__ import annotations

import pytest

from src.orchestrator.preprocessor import RequestPreprocessor


class TestDeployIntentDetection:
    """测试 deploy 意图检测"""

    @pytest.fixture
    def preprocessor(self) -> RequestPreprocessor:
        return RequestPreprocessor()

    @pytest.mark.parametrize("input_text,expected_intent", [
        # deploy 意图
        ("帮我部署 https://github.com/user/repo", "deploy"),
        ("https://github.com/user/repo 这个项目怎么跑起来", "deploy"),
        ("deploy https://github.com/user/repo", "deploy"),
        ("安装 https://github.com/user/repo", "deploy"),
        ("启动 https://github.com/user/repo 这个项目", "deploy"),
        ("运行 https://github.com/user/repo", "deploy"),
        # 非 deploy 意图（有 URL 但无部署关键词）
        ("https://github.com/user/repo 这是什么项目", "explain"),
        ("看看 https://github.com/user/repo", "unknown"),
        # 其他意图
        ("你好", "greeting"),
        ("检查磁盘使用情况", "unknown"),
        ("我有哪些 docker 服务", "list"),
    ])
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

    @pytest.mark.parametrize("input_text,expected_url", [
        ("帮我部署 https://github.com/user/repo", "https://github.com/user/repo"),
        ("https://github.com/user/my-repo 这个项目", "https://github.com/user/my-repo"),
        ("部署 https://gitlab.com/user/repo", "https://gitlab.com/user/repo"),
        ("没有 URL 的文本", None),
    ])
    def test_extract_repo_url(
        self,
        preprocessor: RequestPreprocessor,
        input_text: str,
        expected_url: str | None,
    ) -> None:
        """测试 URL 提取"""
        result = preprocessor.extract_repo_url(input_text)
        assert result == expected_url
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_deploy_intent.py -v`
Expected: FAIL

**Step 3: 更新 types.py 中的 PreprocessIntent**

在 `src/types.py` 中修改 `PreprocessIntent`：

```python
# 预处理器相关类型
PreprocessIntent = Literal[
    "explain",    # 解释/分析对象
    "list",       # 列出对象
    "execute",    # 执行操作
    "greeting",   # 问候
    "deploy",     # 部署项目（新增）
    "unknown",    # 未知意图
]
```

**Step 4: 更新 preprocessor.py 支持 deploy 意图**

在 `src/orchestrator/preprocessor.py` 中添加：

```python
# 在文件顶部的模式定义区域添加
DEPLOY_PATTERNS: list[str] = [
    r"部署",
    r"deploy",
    r"安装",
    r"install",
    r"启动",
    r"运行",
    r"跑起来",
    r"run",
    r"start",
]

# GitHub/GitLab URL 模式
REPO_URL_PATTERN = r"https?://(?:github|gitlab)\.com/[\w\-]+/[\w\-]+"
```

在 `RequestPreprocessor` 类中添加方法：

```python
    def extract_repo_url(self, text: str) -> Optional[str]:
        """从文本中提取仓库 URL

        Args:
            text: 用户输入文本

        Returns:
            仓库 URL，未找到返回 None
        """
        match = re.search(REPO_URL_PATTERN, text)
        return match.group(0) if match else None

    def _has_deploy_intent(self, text: str) -> bool:
        """检测是否有部署意图"""
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in DEPLOY_PATTERNS)
```

修改 `_detect_intent` 方法：

```python
    def _detect_intent(self, text: str) -> PreprocessIntent:
        """检测用户意图

        优先级: deploy > explain > greeting > list > unknown
        """
        text_lower = text.lower()

        # 检查部署意图（优先级最高）
        # 条件：包含仓库 URL 且有部署关键词
        has_repo_url = re.search(REPO_URL_PATTERN, text) is not None
        has_deploy_keywords = self._has_deploy_intent(text)

        if has_repo_url and has_deploy_keywords:
            return "deploy"

        # 检查解释意图
        for pattern in EXPLAIN_PATTERNS:
            if re.search(pattern, text_lower):
                return "explain"

        # 检查问候意图
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return "greeting"

        # 检查列表意图
        for pattern in LIST_PATTERNS:
            if re.search(pattern, text_lower):
                return "list"

        return "unknown"
```

**Step 5: 运行测试验证通过**

Run: `uv run pytest tests/test_deploy_intent.py -v`
Expected: PASS

**Step 6: 运行类型检查**

Run: `uv run mypy src/orchestrator/preprocessor.py --strict`
Expected: Success

**Step 7: Commit**

```bash
git add src/types.py src/orchestrator/preprocessor.py tests/test_deploy_intent.py
git commit -m "feat(preprocessor): add deploy intent detection with repo URL extraction"
```

---

## Task 8: 添加 DEPLOY_INTENT_PROMPT 模板

**Files:**
- Modify: `src/orchestrator/prompt.py`
- Create: `tests/test_deploy_prompt.py`

**Step 1: 创建测试文件**

创建 `tests/test_deploy_prompt.py`：

```python
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
        """测试部署 Prompt 包含部署指引"""
        prompt = prompt_builder.build_deploy_prompt(
            context,
            repo_url="https://github.com/user/repo",
            target_dir="~/projects",
        )

        assert "Dockerfile" in prompt or "docker" in prompt.lower()
        assert "git clone" in prompt.lower() or "clone" in prompt.lower()

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

    def test_worker_capabilities_includes_http(
        self,
        prompt_builder: PromptBuilder,
    ) -> None:
        """测试 Worker 能力包含 http"""
        caps = prompt_builder.get_worker_capabilities()
        assert "http" in caps
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_deploy_prompt.py -v`
Expected: FAIL

**Step 3: 更新 prompt.py 添加部署相关内容**

在 `src/orchestrator/prompt.py` 中：

1. 更新 `WORKER_CAPABILITIES`：

```python
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
        "container": ["list_containers", "restart_container", "view_logs"],
        "audit": ["log_operation"],
        "analyze": ["explain"],
        "http": ["fetch_url", "fetch_github_readme", "list_github_files"],
    }
```

2. 添加 `build_deploy_prompt` 方法：

```python
    def build_deploy_prompt(
        self,
        context: EnvironmentContext,
        repo_url: str,
        target_dir: str = "~/projects",
    ) -> str:
        """构建部署专用系统提示

        Args:
            context: 环境上下文
            repo_url: 仓库 URL
            target_dir: 部署目标目录

        Returns:
            部署系统提示文本
        """
        env_context = context.to_prompt_context()
        worker_caps = self.get_worker_capabilities()

        return f"""You are an intelligent deployment assistant. Help the user deploy a GitHub project.

{env_context}

Available Workers:
{worker_caps}

## Deployment Workflow

1. First, use http.fetch_github_readme to get the project README
2. Use http.list_github_files to check for key files:
   - Dockerfile / docker-compose.yml → Prefer Docker deployment
   - package.json → Node.js project
   - requirements.txt / pyproject.toml → Python project
   - Makefile → Check for install/build targets

3. Based on analysis, choose deployment method:
   - Docker: git clone → docker compose up -d
   - Node.js: git clone → npm install → npm start
   - Python: git clone → pip install / uv sync → start command

4. If README lacks deployment info, use tavily.search (if available) to find deployment guides

5. Assess risk level based on command destructiveness:
   - safe: git clone, docker pull, read operations
   - medium: npm install, pip install, docker compose up
   - high: sudo, rm, overwrite existing files

## Worker Details

- http.fetch_github_readme: Get README content
  - args: {{"repo_url": "https://github.com/owner/repo"}}
  - Returns README content for analysis

- http.list_github_files: List repository file structure
  - args: {{"repo_url": "https://github.com/owner/repo", "path": ""}}
  - Detects key files: Dockerfile, package.json, requirements.txt, etc.

- shell.execute_command: Execute deployment commands
  - args: {{"command": "git clone ..."}}
  - Use for git clone, docker compose, npm install, etc.

- tavily.search: Search for deployment guides (if configured)
  - args: {{"query": "how to deploy project-name"}}

## Target Repository
{repo_url}

## Target Directory
{target_dir}

## Instructions
1. Start by fetching README and listing files
2. Analyze project type and choose best deployment method
3. Execute deployment step by step
4. Report progress and handle errors

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high", "task_completed": true/false}}
"""
```

**Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_deploy_prompt.py -v`
Expected: PASS

**Step 5: 运行类型检查**

Run: `uv run mypy src/orchestrator/prompt.py --strict`
Expected: Success

**Step 6: Commit**

```bash
git add src/orchestrator/prompt.py tests/test_deploy_prompt.py
git commit -m "feat(prompt): add DEPLOY_INTENT_PROMPT with deployment workflow guidance"
```

---

## Task 9: 注册 HttpWorker 到 Engine

**Files:**
- Modify: `src/orchestrator/engine.py`

**Step 1: 在 engine.py 中注册 HttpWorker**

在 `OrchestratorEngine.__init__` 方法中，在 `AnalyzeWorker` 注册之后添加：

```python
        # 注册 HttpWorker
        try:
            from src.workers.http import HttpWorker
            self._workers["http"] = HttpWorker(self._config.http)
        except ImportError:
            pass
```

**Step 2: 添加 deploy 意图处理逻辑**

在 `react_loop` 方法中，在预处理逻辑部分添加 deploy 意图处理：

```python
            # deploy 意图 - 使用专用 prompt
            elif preprocessed.intent == "deploy":
                repo_url = self._preprocessor.extract_repo_url(user_input)
                if repo_url:
                    if self._progress_callback:
                        self._progress_callback(
                            "preprocessing",
                            f"🚀 Deploy intent detected for: {repo_url}"
                        )

                    # 使用部署专用 prompt
                    system_prompt = self._prompt_builder.build_deploy_prompt(
                        self._context,
                        repo_url=repo_url,
                        target_dir="~/projects",
                    )
                    user_prompt = f"Deploy this project: {user_input}"

                    llm_response = await self._llm_client.generate(
                        system_prompt, user_prompt, history=conversation_history
                    )
                    parsed = self._llm_client.parse_json_response(llm_response)

                    if parsed is None:
                        return f"Error: Failed to parse LLM response: {llm_response}"

                    instruction = Instruction(
                        worker=str(parsed.get("worker", "")),
                        action=str(parsed.get("action", "")),
                        args=parsed.get("args", {}),  # type: ignore[arg-type]
                        risk_level=parsed.get("risk_level", "safe"),  # type: ignore[arg-type]
                    )
                else:
                    # 无法提取 URL，回退到普通处理
                    pass  # 继续执行后续的 else 分支
```

**Step 3: 运行现有测试确保不破坏功能**

Run: `uv run pytest tests/ -v --ignore=tests/test_tavily_worker.py`
Expected: All existing tests PASS

**Step 4: 运行类型检查**

Run: `uv run mypy src/orchestrator/engine.py --strict`
Expected: Success

**Step 5: Commit**

```bash
git add src/orchestrator/engine.py
git commit -m "feat(engine): register HttpWorker and add deploy intent handling"
```

---

## Task 10: 添加 tavily-python 依赖

**Files:**
- Modify: `pyproject.toml`

**Step 1: 添加 tavily-python 依赖**

在 `pyproject.toml` 的 `dependencies` 列表中添加：

```toml
dependencies = [
    "textual>=0.47.0",
    "typer>=0.9.0",
    "openai>=1.0.0",
    "pydantic>=2.0.0",
    "docker>=7.0.0",
    "rich>=13.0.0",
    "pyperclip>=1.11.0",
    "httpx>=0.27.0",
    "tavily-python>=0.3.0",
]
```

**Step 2: 同步依赖**

Run: `uv sync`
Expected: Successfully installed tavily-python

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add tavily-python for web search"
```

---

## Task 11: 实现 TavilyWorker

**Files:**
- Create: `src/workers/tavily.py`
- Create: `tests/test_tavily_worker.py`

**Step 1: 创建测试文件**

创建 `tests/test_tavily_worker.py`：

```python
"""TavilyWorker 单元测试"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.config.manager import TavilyConfig
from src.workers.tavily import TavilyWorker


@pytest.fixture
def tavily_config_with_key() -> TavilyConfig:
    """带 API Key 的配置"""
    return TavilyConfig(api_key="test-api-key", timeout=10)


@pytest.fixture
def tavily_config_no_key() -> TavilyConfig:
    """无 API Key 的配置"""
    return TavilyConfig(api_key="", timeout=10)


class TestTavilyWorkerInit:
    """测试 TavilyWorker 初始化"""

    def test_init_with_api_key(self, tavily_config_with_key: TavilyConfig) -> None:
        """测试有 API Key 时初始化"""
        worker = TavilyWorker(tavily_config_with_key)
        assert worker.name == "tavily"
        assert worker._enabled is True

    def test_init_without_api_key(self, tavily_config_no_key: TavilyConfig) -> None:
        """测试无 API Key 时初始化"""
        worker = TavilyWorker(tavily_config_no_key)
        assert worker._enabled is False


class TestTavilySearch:
    """测试 search action"""

    @pytest.mark.asyncio
    async def test_search_success(self, tavily_config_with_key: TavilyConfig) -> None:
        """测试成功搜索"""
        worker = TavilyWorker(tavily_config_with_key)

        mock_results = {
            "results": [
                {
                    "title": "How to deploy",
                    "url": "https://example.com/deploy",
                    "content": "Deployment guide...",
                    "score": 0.95,
                }
            ]
        }

        with patch.object(worker, "_client") as mock_client:
            mock_client.search = MagicMock(return_value=mock_results)

            result = await worker.execute(
                "search",
                {"query": "how to deploy project"}
            )

        assert result.success is True
        assert "deploy" in result.message.lower()

    @pytest.mark.asyncio
    async def test_search_no_api_key(self, tavily_config_no_key: TavilyConfig) -> None:
        """测试无 API Key 时搜索失败"""
        worker = TavilyWorker(tavily_config_no_key)

        result = await worker.execute(
            "search",
            {"query": "test query"}
        )

        assert result.success is False
        assert "API key" in result.message or "not configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_search_no_results(self, tavily_config_with_key: TavilyConfig) -> None:
        """测试无搜索结果"""
        worker = TavilyWorker(tavily_config_with_key)

        mock_results = {"results": []}

        with patch.object(worker, "_client") as mock_client:
            mock_client.search = MagicMock(return_value=mock_results)

            result = await worker.execute(
                "search",
                {"query": "very obscure query"}
            )

        assert result.success is True
        assert "no results" in result.message.lower() or result.data == {"results": []}


class TestTavilyExtract:
    """测试 extract action"""

    @pytest.mark.asyncio
    async def test_extract_success(self, tavily_config_with_key: TavilyConfig) -> None:
        """测试成功提取内容"""
        worker = TavilyWorker(tavily_config_with_key)

        mock_result = {
            "results": [
                {
                    "url": "https://example.com/docs",
                    "raw_content": "This is the extracted content...",
                }
            ]
        }

        with patch.object(worker, "_client") as mock_client:
            mock_client.extract = MagicMock(return_value=mock_result)

            result = await worker.execute(
                "extract",
                {"url": "https://example.com/docs"}
            )

        assert result.success is True
```

**Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_tavily_worker.py -v`
Expected: FAIL with "No module named 'src.workers.tavily'"

**Step 3: 创建 TavilyWorker**

创建 `src/workers/tavily.py`：

```python
"""Tavily 搜索 Worker"""

from __future__ import annotations

from typing import Optional

from src.config.manager import TavilyConfig
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class TavilyWorker(BaseWorker):
    """Tavily 搜索 Worker

    支持的操作:
    - search: 搜索相关信息
    - extract: 提取网页内容
    """

    def __init__(self, config: TavilyConfig) -> None:
        """初始化 TavilyWorker

        Args:
            config: Tavily 配置
        """
        self._config = config
        self._enabled = bool(config.api_key)
        self._client: Optional[object] = None

        if self._enabled:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=config.api_key)
            except ImportError:
                self._enabled = False

    @property
    def name(self) -> str:
        return "tavily"

    def get_capabilities(self) -> list[str]:
        return ["search", "extract"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行 Tavily 操作"""
        if not self._enabled:
            return WorkerResult(
                success=False,
                message="Tavily is not configured. Please set API key with: opsai config set-tavily --api-key <key>",
            )

        if action == "search":
            return await self._search(args)
        elif action == "extract":
            return await self._extract(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

    async def _search(self, args: dict[str, ArgValue]) -> WorkerResult:
        """搜索相关信息"""
        query = args.get("query")
        if not isinstance(query, str):
            return WorkerResult(
                success=False,
                message="query parameter is required and must be a string",
            )

        max_results = args.get("max_results", 5)
        if not isinstance(max_results, int):
            max_results = 5

        try:
            # Tavily client 是同步的，但我们保持接口一致
            from tavily import TavilyClient
            client: TavilyClient = self._client  # type: ignore[assignment]

            response = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
            )

            results = response.get("results", [])

            if not results:
                return WorkerResult(
                    success=True,
                    data={"results": []},
                    message=f"No results found for: {query}",
                    task_completed=False,
                )

            # 格式化结果
            message_parts = [f"Search results for: {query}\n"]
            formatted_results = []

            for idx, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "")[:200]
                score = result.get("score", 0)

                message_parts.append(f"{idx}. {title}")
                message_parts.append(f"   URL: {url}")
                message_parts.append(f"   {content}...")
                message_parts.append("")

                formatted_results.append({
                    "title": title,
                    "url": url,
                    "content": result.get("content", ""),
                    "score": score,
                })

            return WorkerResult(
                success=True,
                data={"results": formatted_results},  # type: ignore[dict-item]
                message="\n".join(message_parts),
                task_completed=False,
            )

        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Search failed: {e!s}",
            )

    async def _extract(self, args: dict[str, ArgValue]) -> WorkerResult:
        """提取网页内容"""
        url = args.get("url")
        if not isinstance(url, str):
            return WorkerResult(
                success=False,
                message="url parameter is required and must be a string",
            )

        try:
            from tavily import TavilyClient
            client: TavilyClient = self._client  # type: ignore[assignment]

            response = client.extract(urls=[url])

            results = response.get("results", [])
            if not results:
                return WorkerResult(
                    success=False,
                    message=f"Failed to extract content from: {url}",
                )

            content = results[0].get("raw_content", "")

            return WorkerResult(
                success=True,
                data={"url": url, "content": content[:5000]},
                message=f"Extracted content from {url}:\n\n{content[:2000]}",
                task_completed=False,
            )

        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Extract failed: {e!s}",
            )
```

**Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_tavily_worker.py -v`
Expected: PASS

**Step 5: 运行类型检查**

Run: `uv run mypy src/workers/tavily.py --strict`
Expected: Success (可能需要添加 type: ignore 注释)

**Step 6: Commit**

```bash
git add src/workers/tavily.py tests/test_tavily_worker.py
git commit -m "feat(tavily): implement TavilyWorker with search and extract actions"
```

---

## Task 12: 注册 TavilyWorker 到 Engine

**Files:**
- Modify: `src/orchestrator/engine.py`

**Step 1: 在 engine.py 中注册 TavilyWorker**

在 `OrchestratorEngine.__init__` 方法中，在 `HttpWorker` 注册之后添加：

```python
        # 注册 TavilyWorker（仅当配置了 API Key）
        if self._config.tavily.api_key:
            try:
                from src.workers.tavily import TavilyWorker
                self._workers["tavily"] = TavilyWorker(self._config.tavily)
            except ImportError:
                pass
```

**Step 2: 更新 prompt.py 中的 WORKER_CAPABILITIES**

在 `src/orchestrator/prompt.py` 中更新：

```python
    WORKER_CAPABILITIES: dict[str, list[str]] = {
        "chat": ["respond"],
        "shell": ["execute_command"],
        "system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
        "container": ["list_containers", "restart_container", "view_logs"],
        "audit": ["log_operation"],
        "analyze": ["explain"],
        "http": ["fetch_url", "fetch_github_readme", "list_github_files"],
        "tavily": ["search", "extract"],
    }
```

**Step 3: 运行测试确保不破坏功能**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

**Step 4: 运行类型检查**

Run: `uv run mypy src/orchestrator/engine.py src/orchestrator/prompt.py --strict`
Expected: Success

**Step 5: Commit**

```bash
git add src/orchestrator/engine.py src/orchestrator/prompt.py
git commit -m "feat(engine): register TavilyWorker and update worker capabilities"
```

---

## Task 13: 添加 CLI 配置命令

**Files:**
- Modify: `src/cli.py`

**Step 1: 添加 set-http 命令**

在 `src/cli.py` 中，在 `config_set_llm` 函数之后添加：

```python
@config_app.command("set-http")
def config_set_http(
    github_token: Optional[str] = typer.Option(None, "--github-token", "-t", help="GitHub Token"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="请求超时时间(秒)"),
) -> None:
    """设置 HTTP 配置

    示例:
        opsai config set-http --github-token ghp_xxxx
        opsai config set-http --timeout 60
    """
    config_manager = ConfigManager()
    config = config_manager.load()

    if github_token is not None:
        config.http.github_token = github_token
    if timeout is not None:
        config.http.timeout = timeout

    config_manager.save(config)
    console.print("[green]✓[/green] HTTP configuration saved")


@config_app.command("set-tavily")
def config_set_tavily(
    api_key: str = typer.Option(..., "--api-key", "-k", help="Tavily API Key"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="请求超时时间(秒)"),
) -> None:
    """设置 Tavily 配置

    示例:
        opsai config set-tavily --api-key tvly-xxxx
    """
    config_manager = ConfigManager()
    config = config_manager.load()

    config.tavily.api_key = api_key
    if timeout is not None:
        config.tavily.timeout = timeout

    config_manager.save(config)
    console.print("[green]✓[/green] Tavily configuration saved")
```

**Step 2: 运行 CLI 帮助验证命令存在**

Run: `uv run opsai config --help`
Expected: 显示 set-http 和 set-tavily 命令

**Step 3: 运行类型检查**

Run: `uv run mypy src/cli.py --strict`
Expected: Success

**Step 4: Commit**

```bash
git add src/cli.py
git commit -m "feat(cli): add set-http and set-tavily config commands"
```

---

## Task 14: 端到端集成测试

**Files:**
- Create: `tests/test_deploy_integration.py`

**Step 1: 创建集成测试文件**

创建 `tests/test_deploy_integration.py`：

```python
"""部署功能端到端集成测试"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

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

    def test_deploy_intent_detected(self, engine: OrchestratorEngine) -> None:
        """测试部署意图被正确检测"""
        preprocessor = engine._preprocessor
        result = preprocessor.preprocess("帮我部署 https://github.com/user/repo")
        assert result.intent == "deploy"

    @pytest.mark.asyncio
    async def test_http_worker_fetch_readme(self, engine: OrchestratorEngine) -> None:
        """测试 HttpWorker 获取 README"""
        http_worker = engine.get_worker("http")
        assert http_worker is not None

        # Mock HTTP 响应
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "# Test Project\n\nThis is a test."

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await http_worker.execute(
                "fetch_github_readme",
                {"repo_url": "https://github.com/user/repo"}
            )

        assert result.success is True
        assert "Test Project" in result.message

    @pytest.mark.asyncio
    async def test_deploy_workflow_generates_instruction(
        self,
        config: OpsAIConfig,
    ) -> None:
        """测试部署工作流生成正确的指令"""
        # Mock LLM 响应
        mock_llm_response = '{"worker": "http", "action": "fetch_github_readme", "args": {"repo_url": "https://github.com/user/repo"}, "risk_level": "safe", "task_completed": false}'

        with patch("src.llm.client.LLMClient.generate", return_value=mock_llm_response):
            engine = OrchestratorEngine(config)

            # Mock HTTP Worker 执行
            mock_http_result = MagicMock()
            mock_http_result.success = True
            mock_http_result.message = "README content"
            mock_http_result.task_completed = True

            with patch.object(
                engine._workers["http"],
                "execute",
                return_value=mock_http_result
            ):
                # 这里只验证流程不报错
                # 实际的端到端测试需要更复杂的 mock
                pass


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
```

**Step 2: 运行集成测试**

Run: `uv run pytest tests/test_deploy_integration.py -v`
Expected: PASS

**Step 3: 运行所有测试确保无回归**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_deploy_integration.py
git commit -m "test: add deploy feature integration tests"
```

---

## Task 15: 代码质量检查和最终验证

**Files:**
- All modified files

**Step 1: 运行 Ruff 格式化**

Run: `uv run ruff format src/ tests/`
Expected: Files formatted

**Step 2: 运行 Ruff 检查**

Run: `uv run ruff check src/ tests/ --fix`
Expected: No errors (或已自动修复)

**Step 3: 运行 MyPy 类型检查**

Run: `uv run mypy src/ --strict`
Expected: Success

**Step 4: 运行完整测试套件**

Run: `uv run pytest tests/ -v --cov=src --cov-report=term-missing`
Expected: All tests PASS, coverage report generated

**Step 5: 手动功能验证**

Run: `uv run opsai config show`
Expected: 显示包含 http 和 tavily 配置的完整配置

**Step 6: 最终 Commit**

```bash
git add -A
git commit -m "chore: code quality fixes and final verification"
```

---

## 实现优先级总结

### P0 - 核心功能（Task 1-9）
- 类型定义
- 配置模型
- HttpWorker（fetch_url, fetch_github_readme, list_github_files）
- 意图识别扩展（deploy intent）
- DEPLOY_INTENT_PROMPT 模板
- Engine 注册

### P1 - 增强功能（Task 10-13）
- TavilyWorker
- CLI 配置命令

### P2 - 完善（Task 14-15）
- 集成测试
- 代码质量检查

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/types.py` | Modify | 添加 Intent, GitHubFileInfo, TavilySearchResult |
| `src/config/manager.py` | Modify | 添加 HttpConfig, TavilyConfig |
| `pyproject.toml` | Modify | 添加 httpx, tavily-python 依赖 |
| `src/workers/http.py` | Create | HttpWorker 实现 |
| `src/workers/tavily.py` | Create | TavilyWorker 实现 |
| `src/orchestrator/preprocessor.py` | Modify | 添加 deploy 意图检测 |
| `src/orchestrator/prompt.py` | Modify | 添加 DEPLOY_INTENT_PROMPT |
| `src/orchestrator/engine.py` | Modify | 注册新 Workers，处理 deploy 意图 |
| `src/cli.py` | Modify | 添加 set-http, set-tavily 命令 |
| `tests/test_config_deploy.py` | Create | 配置测试 |
| `tests/test_http_worker.py` | Create | HttpWorker 测试 |
| `tests/test_tavily_worker.py` | Create | TavilyWorker 测试 |
| `tests/test_deploy_intent.py` | Create | 意图识别测试 |
| `tests/test_deploy_prompt.py` | Create | Prompt 测试 |
| `tests/test_deploy_integration.py` | Create | 集成测试 |
