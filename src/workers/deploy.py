"""GitHub 项目部署 Worker"""

from __future__ import annotations

import os
import re
import shlex
from typing import Optional, Union, cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.http import HttpWorker
from src.workers.shell import ShellWorker

# 项目类型检测规则
PROJECT_TYPE_DETECTION: dict[str, list[str]] = {
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "python": ["requirements.txt", "pyproject.toml", "setup.py"],
    "nodejs": ["package.json"],
    "go": ["go.mod"],
    "rust": ["Cargo.toml"],
}

# 项目类型对应的部署命令
DEPLOY_COMMANDS: dict[str, dict[str, str]] = {
    "docker": {
        "install": "docker compose up -d",
        "start": "docker compose up -d",
        "check": "docker compose ps",
    },
    "python": {
        "install": "pip install -r requirements.txt",
        "install_uv": "uv sync",
        "start": "python main.py",
    },
    "nodejs": {
        "install": "npm install",
        "start": "npm start",
    },
    "go": {
        "install": "go mod download",
        "start": "go run .",
    },
    "rust": {
        "install": "cargo build --release",
        "start": "./target/release/*",
    },
}


class DeployWorker(BaseWorker):
    """GitHub 项目部署 Worker

    支持的操作:
    - analyze_repo: 分析仓库结构，返回项目类型和部署建议
    - clone_repo: 克隆仓库到指定目录
    - setup_env: 配置环境（复制 .env.example、安装依赖）
    - start_service: 启动服务
    """

    def __init__(self, http_worker: HttpWorker, shell_worker: ShellWorker) -> None:
        """初始化 DeployWorker

        Args:
            http_worker: HTTP Worker 实例
            shell_worker: Shell Worker 实例
        """
        self._http = http_worker
        self._shell = shell_worker

    @property
    def name(self) -> str:
        return "deploy"

    def get_capabilities(self) -> list[str]:
        # 简化对外能力：只暴露一键部署
        # 内部方法（analyze_repo, clone_repo, setup_env, start_service）仍保留供内部调用
        return ["deploy"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行部署操作"""
        if action == "deploy":
            return await self._one_click_deploy(args)
        # 保留内部方法（向后兼容）
        elif action == "analyze_repo":
            return await self._analyze_repo(args)
        elif action == "clone_repo":
            return await self._clone_repo(args)
        elif action == "setup_env":
            return await self._setup_env(args)
        elif action == "start_service":
            return await self._start_service(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

    async def _one_click_deploy(self, args: dict[str, ArgValue]) -> WorkerResult:
        """一键部署 GitHub 项目

        Args:
            args: {
                "repo_url": "https://github.com/owner/repo",
                "target_dir": "~/projects"  # 可选
            }

        Returns:
            WorkerResult: 部署结果（包含所有步骤的摘要）
        """
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required",
            )

        target_dir = args.get("target_dir", "~/projects")
        if not isinstance(target_dir, str):
            target_dir = "~/projects"

        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        steps_log: list[str] = []

        # Step 1: 分析项目
        steps_log.append("📋 Step 1/4: 分析项目结构...")
        analyze_result = await self._analyze_repo({"repo_url": repo_url})
        if not analyze_result.success:
            return WorkerResult(
                success=False,
                message=f"❌ 分析失败：{analyze_result.message}",
            )

        project_type = "unknown"
        if analyze_result.data and isinstance(analyze_result.data, dict):
            project_type = str(analyze_result.data.get("project_type", "unknown"))
        steps_log.append(f"  ✓ 检测到项目类型：{project_type}")

        # Step 2: 克隆仓库
        steps_log.append("📦 Step 2/4: 克隆仓库...")
        clone_result = await self._clone_repo(
            {
                "repo_url": repo_url,
                "target_dir": target_dir,
                "dry_run": dry_run,
            }
        )
        if not clone_result.success:
            return WorkerResult(
                success=False,
                message="\n".join(steps_log) + f"\n❌ 克隆失败：{clone_result.message}",
            )

        project_dir = ""
        already_exists = False
        if clone_result.data and isinstance(clone_result.data, dict):
            project_dir = str(clone_result.data.get("path", ""))
            already_exists = bool(clone_result.data.get("already_exists", False))

        if already_exists:
            steps_log.append(f"  ⚠️ 项目已存在：{project_dir}")
        else:
            steps_log.append(f"  ✓ 克隆完成：{project_dir}")

        # Step 3: 配置环境
        steps_log.append("⚙️  Step 3/4: 配置环境...")
        setup_result = await self._setup_env(
            {
                "project_dir": project_dir,
                "project_type": project_type,
                "dry_run": dry_run,
            }
        )
        if not setup_result.success:
            return WorkerResult(
                success=False,
                message="\n".join(steps_log) + f"\n❌ 环境配置失败：{setup_result.message}",
            )
        steps_log.append("  ✓ 环境配置完成")

        # Step 4: 启动服务
        steps_log.append("🚀 Step 4/4: 启动服务...")
        start_result = await self._start_service(
            {
                "project_dir": project_dir,
                "project_type": project_type,
                "dry_run": dry_run,
            }
        )
        if not start_result.success:
            # 启动失败时，提供详细的错误提示
            error_msg = start_result.message
            suggestions = self._generate_error_suggestions(project_type, error_msg)
            return WorkerResult(
                success=False,
                message="\n".join(steps_log)
                + f"\n❌ 启动失败：{error_msg}\n\n"
                + f"💡 可能的解决方法：\n{suggestions}",
            )

        steps_log.append("  ✓ 服务启动成功！")

        # 成功摘要
        summary = "\n".join(steps_log)
        summary += "\n\n✅ 部署完成！"
        summary += f"\n📂 项目路径：{project_dir}"
        summary += f"\n🎯 项目类型：{project_type}"

        if dry_run:
            summary = "[DRY-RUN 模式]\n\n" + summary

        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {
                    "project_dir": project_dir,
                    "project_type": project_type,
                    "repo_url": repo_url,
                },
            ),
            message=summary,
            task_completed=True,
            simulated=bool(dry_run),
        )

    def _generate_error_suggestions(self, project_type: str, error_msg: str) -> str:
        """根据错误信息生成建议"""
        suggestions: list[str] = []
        error_lower = error_msg.lower()

        if "permission denied" in error_lower:
            suggestions.append("1. 检查文件权限：chmod +x start.sh")
            suggestions.append("2. 使用 sudo（如果需要）")

        if "port" in error_lower or "address already in use" in error_lower:
            suggestions.append("1. 检查端口占用：lsof -i :端口号")
            suggestions.append("2. 修改配置文件中的端口")

        if ".env" in error_lower or "environment" in error_lower:
            suggestions.append("1. 检查 .env 文件是否存在")
            suggestions.append("2. 从 .env.example 复制并填写必要配置")

        if project_type == "docker" and "docker" in error_lower:
            suggestions.append("1. 确保 Docker 正在运行：docker ps")
            suggestions.append("2. 检查 docker-compose.yml 配置")

        if not suggestions:
            suggestions.append("1. 查看项目 README 了解部署要求")
            suggestions.append("2. 检查项目目录中的错误日志")

        return "\n".join(suggestions)

    def _parse_github_url(self, url: str) -> Optional[tuple[str, str]]:
        """解析 GitHub URL，提取 owner 和 repo"""
        pattern = r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+?)(?:\.git)?/?$"
        match = re.match(pattern, url)
        if match:
            return (match.group(1), match.group(2))
        return None

    def _detect_project_type(self, key_files: list[str]) -> tuple[str, list[str]]:
        """检测项目类型

        Args:
            key_files: 仓库中的关键文件列表

        Returns:
            (项目类型, 匹配的文件列表)
        """
        # 优先检测 Docker（如果有 Dockerfile 或 compose 文件）
        for file in key_files:
            if file.lower() in ["dockerfile", "docker-compose.yml", "docker-compose.yaml"]:
                matched = [
                    f
                    for f in key_files
                    if f.lower() in [x.lower() for x in PROJECT_TYPE_DETECTION["docker"]]
                ]
                return ("docker", matched)

        # 其他项目类型检测
        for project_type, indicators in PROJECT_TYPE_DETECTION.items():
            matched = [f for f in key_files if f.lower() in [x.lower() for x in indicators]]
            if matched:
                return (project_type, matched)

        return ("unknown", [])

    async def _analyze_repo(self, args: dict[str, ArgValue]) -> WorkerResult:
        """分析仓库结构，返回项目类型和部署建议"""
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
                message=f"Invalid GitHub URL format: {repo_url}",
            )

        owner, repo = parsed

        # 1. 获取 README
        readme_result = await self._http.execute(
            "fetch_github_readme",
            {"repo_url": repo_url},
        )
        readme_content = ""
        if readme_result.success and readme_result.data:
            readme_content = str(readme_result.data.get("content", ""))

        # 2. 获取文件列表
        files_result = await self._http.execute(
            "list_github_files",
            {"repo_url": repo_url},
        )

        key_files: list[str] = []
        if files_result.success and files_result.data:
            key_files_str = files_result.data.get("key_files", "")
            if isinstance(key_files_str, str) and key_files_str:
                key_files = [f.strip() for f in key_files_str.split(",")]

        # 3. 检测项目类型
        project_type, matched_files = self._detect_project_type(key_files)

        # 4. 生成部署建议
        deploy_commands = DEPLOY_COMMANDS.get(project_type, {})

        # 构建分析报告
        report_parts = [
            f"## Repository Analysis: {owner}/{repo}",
            "",
            f"**Project Type:** {project_type}",
            f"**Key Files:** {', '.join(key_files) if key_files else 'None detected'}",
            f"**Matched Indicators:** {', '.join(matched_files) if matched_files else 'None'}",
            "",
        ]

        if deploy_commands:
            report_parts.append("**Suggested Deployment Steps:**")
            step = 1
            report_parts.append(f"{step}. Clone: `git clone {repo_url}`")
            step += 1

            if "install" in deploy_commands:
                report_parts.append(f"{step}. Install: `{deploy_commands['install']}`")
                step += 1

            if "start" in deploy_commands:
                report_parts.append(f"{step}. Start: `{deploy_commands['start']}`")
        else:
            report_parts.append("**Note:** Unable to detect project type automatically.")
            report_parts.append("Please check the README for deployment instructions.")

        # 添加 README 摘要
        if readme_content:
            # 截取前 500 字符作为摘要
            readme_summary = readme_content[:500]
            if len(readme_content) > 500:
                readme_summary += "..."
            report_parts.extend(
                [
                    "",
                    "**README Summary:**",
                    readme_summary,
                ]
            )

        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {
                    "owner": owner,
                    "repo": repo,
                    "project_type": project_type,
                    "key_files": ", ".join(key_files),
                },
            ),
            message="\n".join(report_parts),
            task_completed=False,  # 需要后续步骤
        )

    async def _clone_repo(self, args: dict[str, ArgValue]) -> WorkerResult:
        """克隆仓库到指定目录"""
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required and must be a string",
            )

        target_dir = args.get("target_dir", "~/projects")
        if not isinstance(target_dir, str):
            target_dir = "~/projects"

        # 展开 ~ 路径
        target_dir = os.path.expanduser(target_dir)

        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        parsed = self._parse_github_url(repo_url)
        if not parsed:
            return WorkerResult(
                success=False,
                message=f"Invalid GitHub URL format: {repo_url}",
            )

        owner, repo = parsed
        clone_path = os.path.join(target_dir, repo)

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would execute:\n"
                f"  1. mkdir -p {target_dir}\n"
                f"  2. git clone {repo_url} {clone_path}",
                simulated=True,
                task_completed=False,
            )

        # 使用 shlex.quote 防止命令注入
        safe_target_dir = shlex.quote(target_dir)
        safe_clone_path = shlex.quote(clone_path)
        safe_repo_url = shlex.quote(repo_url)

        # 创建目标目录
        mkdir_result = await self._shell.execute(
            "execute_command",
            {"command": f"mkdir -p {safe_target_dir}"},
        )
        if not mkdir_result.success:
            return WorkerResult(
                success=False,
                message=f"Failed to create directory: {mkdir_result.message}",
            )

        # 检查是否已存在
        check_result = await self._shell.execute(
            "execute_command",
            {"command": f"test -d {safe_clone_path} && echo 'DIR_EXISTS' || echo 'DIR_NOT_EXISTS'"},
        )
        if check_result.success and check_result.data:
            stdout = check_result.data.get("stdout", "")
            if isinstance(stdout, str) and "DIR_EXISTS" in stdout and "NOT" not in stdout:
                return WorkerResult(
                    success=True,
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {"path": clone_path, "already_exists": True},
                    ),
                    message=f"Repository already exists at {clone_path}. Skipping clone.",
                    task_completed=False,
                )

        # 克隆仓库
        clone_result = await self._shell.execute(
            "execute_command",
            {"command": f"git clone {safe_repo_url} {safe_clone_path}"},
        )

        if clone_result.success:
            return WorkerResult(
                success=True,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {"path": clone_path, "already_exists": False},
                ),
                message=f"Successfully cloned {owner}/{repo} to {clone_path}",
                task_completed=False,
            )
        else:
            return WorkerResult(
                success=False,
                message=f"Failed to clone repository: {clone_result.message}",
            )

    async def _setup_env(self, args: dict[str, ArgValue]) -> WorkerResult:
        """配置环境（复制 .env.example、安装依赖）"""
        project_dir = args.get("project_dir")
        if not isinstance(project_dir, str):
            return WorkerResult(
                success=False,
                message="project_dir parameter is required and must be a string",
            )

        project_type = args.get("project_type", "unknown")
        if not isinstance(project_type, str):
            project_type = "unknown"

        # 展开 ~ 路径
        project_dir = os.path.expanduser(project_dir)

        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        setup_steps: list[str] = []

        # 使用 shlex.quote 防止命令注入
        safe_project_dir = shlex.quote(project_dir)

        # 1. 检查并复制 .env.example
        env_example_path = shlex.quote(os.path.join(project_dir, ".env.example"))
        env_path = shlex.quote(os.path.join(project_dir, ".env"))
        env_check = f"test -f {env_example_path} && echo 'has_env_example' || echo 'no_env_example'"

        if dry_run:
            setup_steps.append(f"Check for .env.example: {env_check}")
            setup_steps.append("If exists: cp .env.example .env")
        else:
            check_result = await self._shell.execute(
                "execute_command",
                {"command": env_check},
            )
            if check_result.success and check_result.data:
                stdout = check_result.data.get("stdout", "")
                if isinstance(stdout, str) and "has_env_example" in stdout:
                    # 复制 .env.example 到 .env
                    cp_result = await self._shell.execute(
                        "execute_command",
                        {"command": f"cp {env_example_path} {env_path}"},
                    )
                    if cp_result.success:
                        setup_steps.append("Copied .env.example to .env")
                    else:
                        setup_steps.append(f"Failed to copy .env: {cp_result.message}")

        # 2. 安装依赖
        deploy_commands = DEPLOY_COMMANDS.get(project_type, {})
        install_cmd = deploy_commands.get("install")

        if install_cmd:
            if dry_run:
                setup_steps.append(f"Install dependencies: cd {project_dir} && {install_cmd}")
                return WorkerResult(
                    success=True,
                    message="[DRY-RUN] Would setup environment:\n"
                    + "\n".join(f"  - {s}" for s in setup_steps),
                    simulated=True,
                    task_completed=False,
                )

            install_result = await self._shell.execute(
                "execute_command",
                {"command": install_cmd, "working_dir": project_dir},
            )
            if install_result.success:
                setup_steps.append(f"Dependencies installed: {install_cmd}")
            else:
                return WorkerResult(
                    success=False,
                    message=f"Failed to install dependencies: {install_result.message}",
                )

        if dry_run:
            return WorkerResult(
                success=True,
                message="[DRY-RUN] Would setup environment:\n"
                + "\n".join(f"  - {s}" for s in setup_steps),
                simulated=True,
                task_completed=False,
            )

        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {"project_dir": project_dir, "project_type": project_type},
            ),
            message="Environment setup complete:\n" + "\n".join(f"  - {s}" for s in setup_steps),
            task_completed=False,
        )

    async def _start_service(self, args: dict[str, ArgValue]) -> WorkerResult:
        """启动服务"""
        project_dir = args.get("project_dir")
        if not isinstance(project_dir, str):
            return WorkerResult(
                success=False,
                message="project_dir parameter is required and must be a string",
            )

        project_type = args.get("project_type", "unknown")
        if not isinstance(project_type, str):
            project_type = "unknown"

        # 展开 ~ 路径
        project_dir = os.path.expanduser(project_dir)
        safe_project_dir = shlex.quote(project_dir)

        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        deploy_commands = DEPLOY_COMMANDS.get(project_type, {})
        start_cmd = deploy_commands.get("start")

        if not start_cmd:
            return WorkerResult(
                success=False,
                message=f"No start command defined for project type: {project_type}",
            )

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would start service:\n  cd {safe_project_dir} && {start_cmd}",
                simulated=True,
                task_completed=True,
            )

        # 启动服务
        start_result = await self._shell.execute(
            "execute_command",
            {"command": start_cmd, "working_dir": project_dir},
        )

        if start_result.success:
            return WorkerResult(
                success=True,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {
                        "project_dir": project_dir,
                        "project_type": project_type,
                        "start_command": start_cmd,
                    },
                ),
                message=f"Service started successfully!\n"
                f"  Directory: {project_dir}\n"
                f"  Command: {start_cmd}\n"
                f"  Output: {start_result.message}",
                task_completed=True,
            )
        else:
            return WorkerResult(
                success=False,
                message=f"Failed to start service: {start_result.message}",
            )
