"""HTTP 请求 Worker"""

from __future__ import annotations

import re
from typing import Optional, Union, cast
from urllib.parse import urlparse

import httpx

from src.config.manager import HttpConfig
from src.types import ActionParam, ArgValue, ToolAction, WorkerResult
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

    @property
    def description(self) -> str:
        return "HTTP client for fetching URLs and GitHub content"

    def get_capabilities(self) -> list[str]:
        return ["fetch_url", "fetch_github_readme", "list_github_files"]

    def get_actions(self) -> list[ToolAction]:
        return [
            ToolAction(
                name="fetch_url",
                description="Fetch content from any HTTP/HTTPS URL. Returns up to 5000 chars.",
                params=[
                    ActionParam(
                        name="url",
                        param_type="string",
                        description="Full URL (e.g. https://example.com/page)",
                        required=True,
                    ),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="fetch_github_readme",
                description=(
                    "Fetch README from a GitHub repository (tries main/master, README.md/rst)."
                ),
                params=[
                    ActionParam(
                        name="repo_url",
                        param_type="string",
                        description="GitHub repo URL: https://github.com/owner/repo",
                        required=True,
                    ),
                ],
                risk_level="safe",
            ),
            ToolAction(
                name="list_github_files",
                description="List files and dirs at repo root or specified path via GitHub API.",
                params=[
                    ActionParam(
                        name="repo_url",
                        param_type="string",
                        description="GitHub repo URL: https://github.com/owner/repo",
                        required=True,
                    ),
                    ActionParam(
                        name="path",
                        param_type="string",
                        description="Sub-path in repo (default: root)",
                        required=False,
                    ),
                ],
                risk_level="safe",
            ),
        ]

    def _is_valid_url(self, url: str) -> bool:
        """验证 URL 格式"""
        try:
            result = urlparse(url)
            return all([result.scheme in ("http", "https"), result.netloc])
        except Exception:
            return False

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
        pattern = r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+?)(?:\.git)?/?$"
        match = re.match(pattern, url)
        if match:
            return (match.group(1), match.group(2))
        return None

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

                content = response.text[:5000]  # 限制长度

                return WorkerResult(
                    success=True,
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {"url": url, "content": content},
                    ),
                    message=f"Fetched content from {url}:\n\n{content[:2000]}",
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
                message=f"Invalid GitHub URL format: {repo_url}. "
                "Expected: https://github.com/owner/repo",
            )

        owner, repo = parsed

        # 构建 raw.githubusercontent.com URL
        # 先尝试 main 分支，失败则尝试 master
        branches = ["main", "master"]
        readme_files = ["README.md", "readme.md", "README.rst", "README"]

        headers: dict[str, str] = {}
        if self._github_token:
            headers["Authorization"] = f"token {self._github_token}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for branch in branches:
                for readme_file in readme_files:
                    raw_url = (
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{readme_file}"
                    )
                    try:
                        response = await client.get(raw_url, headers=headers)
                        if response.status_code == 200:
                            content = response.text
                            return WorkerResult(
                                success=True,
                                data=cast(
                                    dict[str, Union[str, int, bool]],
                                    {
                                        "owner": owner,
                                        "repo": repo,
                                        "branch": branch,
                                        "readme_file": readme_file,
                                        "content": content[:10000],
                                    },
                                ),
                                message=f"README from {owner}/{repo} "
                                f"({branch}/{readme_file}):\n\n{content[:3000]}",
                                task_completed=False,  # 需要 LLM 分析
                            )
                    except httpx.HTTPStatusError:
                        continue
                    except Exception:
                        continue

        return WorkerResult(
            success=False,
            message=f"README not found in {owner}/{repo}. "
            f"Tried branches: {branches}, files: {readme_files}",
        )

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

        headers: dict[str, str] = {
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
                    "Dockerfile",
                    "docker-compose.yml",
                    "docker-compose.yaml",
                    "package.json",
                    "requirements.txt",
                    "pyproject.toml",
                    "Makefile",
                    "setup.py",
                    "go.mod",
                    "Cargo.toml",
                }

                for item in data:
                    file_info = {
                        "name": str(item.get("name", "")),
                        "type": str(item.get("type", "")),
                        "path": str(item.get("path", "")),
                    }
                    files.append(file_info)

                    if item.get("name") in key_file_names:
                        key_files.append(str(item.get("name", "")))

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
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {"files_count": len(files), "key_files": ", ".join(key_files)},
                    ),
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
