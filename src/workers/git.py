"""Git 操作 Worker

核心原则：显式路径优先
- clone 必须有明确的 target_dir
- 不依赖隐式工作目录
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union, cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.path_utils import normalize_path
from src.workers.shell import ShellWorker


class GitWorker(BaseWorker):
    """Git 操作 Worker

    支持的操作:
    - clone: 克隆仓库（显式路径优先）
    - pull: 拉取更新
    - status: 查看状态

    设计原则：
    - target_dir 参数显式传递，消除隐式依赖
    - 即使用户未指定，也会显式使用 cwd 并在结果中明确标注
    """

    def __init__(self) -> None:
        """初始化 GitWorker"""
        self._shell = ShellWorker()

    @property
    def name(self) -> str:
        return "git"

    def get_capabilities(self) -> list[str]:
        return ["clone", "pull", "status"]

    def _extract_repo_name(self, url: str) -> str:
        """从 Git URL 提取仓库名

        支持格式：
        - https://github.com/user/repo.git
        - https://github.com/user/repo
        - git@github.com:user/repo.git

        Args:
            url: Git 仓库 URL

        Returns:
            仓库名称
        """
        # 移除 .git 后缀
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]

        # 提取最后一段作为仓库名
        match = re.search(r"[/:]([^/:]+)$", url)
        if match:
            return match.group(1)

        # 兜底：返回整个 URL 的最后一段
        return url.split("/")[-1] or "repo"

    async def _clone(self, args: dict[str, ArgValue]) -> WorkerResult:
        """克隆仓库

        Args:
            args: 参数字典
                - url: 仓库 URL（必需）
                - target_dir: 目标目录（可选，默认使用 cwd）
                - dry_run: 是否模拟执行

        Returns:
            WorkerResult
        """
        url = args.get("url")
        if not isinstance(url, str) or not url:
            return WorkerResult(
                success=False,
                message="url is required and must be a string",
            )

        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        # 显式路径优先：获取 target_dir
        target_dir = args.get("target_dir")
        if target_dir is None:
            # 显式使用 cwd，并在结果中明确标注
            target_dir = os.getcwd()
            path_source = "current working directory"
        else:
            if not isinstance(target_dir, str):
                return WorkerResult(
                    success=False,
                    message="target_dir must be a string",
                )
            target_dir = normalize_path(target_dir)
            path_source = "specified path"

        # 提取仓库名
        repo_name = self._extract_repo_name(url)
        full_path = str(Path(target_dir) / repo_name)

        # 构建命令
        command = f"git clone {url} {full_path}"

        if dry_run:
            return WorkerResult(
                success=True,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {
                        "url": url,
                        "target_dir": target_dir,
                        "full_path": full_path,
                        "repo_name": repo_name,
                        "path_source": path_source,
                    },
                ),
                message=f"[DRY-RUN] Would clone {url} to {full_path} ({path_source})",
                simulated=True,
            )

        # 检查目标目录是否存在
        if Path(full_path).exists():
            return WorkerResult(
                success=False,
                message=f"Target directory already exists: {full_path}",
            )

        # 确保父目录存在
        Path(target_dir).mkdir(parents=True, exist_ok=True)

        # 执行 clone
        result = await self._shell.execute(
            "execute_command",
            {"command": command, "working_dir": target_dir},
        )

        if result.success:
            return WorkerResult(
                success=True,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {
                        "url": url,
                        "target_dir": target_dir,
                        "full_path": full_path,
                        "repo_name": repo_name,
                        "path_source": path_source,
                    },
                ),
                message=f"Cloned {url} to {full_path} ({path_source})",
                task_completed=True,
            )

        return result

    async def _pull(self, args: dict[str, ArgValue]) -> WorkerResult:
        """拉取更新

        Args:
            args: 参数字典
                - repo_dir: 仓库目录（必需）
                - dry_run: 是否模拟执行

        Returns:
            WorkerResult
        """
        repo_dir = args.get("repo_dir")
        if not isinstance(repo_dir, str) or not repo_dir:
            return WorkerResult(
                success=False,
                message="repo_dir is required and must be a string",
            )

        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        # 展开路径
        repo_dir = str(Path(repo_dir).expanduser())

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would pull in {repo_dir}",
                simulated=True,
            )

        # 检查目录是否存在
        if not Path(repo_dir).exists():
            return WorkerResult(
                success=False,
                message=f"Repository directory not found: {repo_dir}",
            )

        # 执行 pull
        result = await self._shell.execute(
            "execute_command",
            {"command": "git pull", "working_dir": repo_dir},
        )

        if result.success:
            return WorkerResult(
                success=True,
                data=result.data,
                message=f"Pulled updates in {repo_dir}",
                task_completed=True,
            )

        return result

    async def _status(self, args: dict[str, ArgValue]) -> WorkerResult:
        """查看仓库状态

        Args:
            args: 参数字典
                - repo_dir: 仓库目录（必需）

        Returns:
            WorkerResult
        """
        repo_dir = args.get("repo_dir")
        if not isinstance(repo_dir, str) or not repo_dir:
            return WorkerResult(
                success=False,
                message="repo_dir is required and must be a string",
            )

        # 展开路径
        repo_dir = str(Path(repo_dir).expanduser())

        # 检查目录是否存在
        if not Path(repo_dir).exists():
            return WorkerResult(
                success=False,
                message=f"Repository directory not found: {repo_dir}",
            )

        # 执行 status
        result = await self._shell.execute(
            "execute_command",
            {"command": "git status", "working_dir": repo_dir},
        )

        if result.success:
            return WorkerResult(
                success=True,
                data=result.data,
                message=result.message,
                task_completed=True,
            )

        return result

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行 Git 操作

        Args:
            action: 动作名称
            args: 参数字典

        Returns:
            WorkerResult
        """
        if action == "clone":
            return await self._clone(args)
        elif action == "pull":
            return await self._pull(args)
        elif action == "status":
            return await self._status(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )
