"""GitHub 项目部署 Worker - LLM 驱动的智能部署"""

from __future__ import annotations

import os
import re
import shlex
from typing import Optional, Union, cast

from src.llm.client import LLMClient
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.deploy.diagnose import DeployDiagnoser
from src.workers.deploy.executor import DeployExecutor
from src.workers.deploy.planner import DeployPlanner
from src.workers.deploy.types import (
    AskUserCallback,
    ConfirmationCallback,
    ProgressCallback,
)
from src.workers.http import HttpWorker
from src.workers.shell import ShellWorker


class DeployWorker(BaseWorker):
    """GitHub 项目部署 Worker - LLM 驱动的智能部署

    核心理念：
    - 不再使用硬编码规则，由 LLM 分析项目并生成部署计划
    - 遇到错误时自动诊断并重试
    - 只在需要 sudo 或破坏性操作时询问用户
    """

    def __init__(
        self,
        http_worker: HttpWorker,
        shell_worker: ShellWorker,
        llm_client: LLMClient,
        progress_callback: ProgressCallback = None,
        confirmation_callback: ConfirmationCallback = None,
        ask_user_callback: AskUserCallback = None,
    ) -> None:
        self._http = http_worker
        self._shell = shell_worker
        self._llm = llm_client
        self._progress_callback = progress_callback
        self._confirmation_callback = confirmation_callback
        self._ask_user_callback = ask_user_callback

        # 初始化子模块
        self._planner = DeployPlanner(shell_worker, llm_client, progress_callback)
        self._diagnoser = DeployDiagnoser(
            shell_worker,
            llm_client,
            progress_callback,
            confirmation_callback,
            ask_user_callback,
        )
        self._executor = DeployExecutor(
            shell_worker,
            self._diagnoser,
            progress_callback,
            confirmation_callback,
        )

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback
        self._planner.set_progress_callback(callback)
        self._diagnoser.set_progress_callback(callback)
        self._executor.set_progress_callback(callback)

    def set_confirmation_callback(self, callback: ConfirmationCallback) -> None:
        self._confirmation_callback = callback
        self._diagnoser.set_confirmation_callback(callback)
        self._executor.set_confirmation_callback(callback)

    def set_ask_user_callback(self, callback: AskUserCallback) -> None:
        self._ask_user_callback = callback
        self._diagnoser.set_ask_user_callback(callback)

    def _report_progress(self, step: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(step, message)

    @property
    def name(self) -> str:
        return "deploy"

    def get_capabilities(self) -> list[str]:
        return ["deploy"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        if action == "deploy":
            return await self._intelligent_deploy(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

    def _parse_github_url(self, url: str) -> Optional[tuple[str, str]]:
        pattern = r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+?)(?:\.git)?/?$"
        match = re.match(pattern, url)
        if match:
            return (match.group(1), match.group(2))
        return None

    async def _intelligent_deploy(self, args: dict[str, ArgValue]) -> WorkerResult:
        """LLM 驱动的智能部署"""
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(success=False, message="repo_url parameter is required")

        target_dir = args.get("target_dir")
        if not isinstance(target_dir, str) or not target_dir.strip():
            target_dir = os.getcwd()
        else:
            target_dir = target_dir.strip()

        dry_run_value = args.get("dry_run", False)
        dry_run = False
        if isinstance(dry_run_value, bool):
            dry_run = dry_run_value
        elif isinstance(dry_run_value, str):
            dry_run = dry_run_value.lower() == "true"

        steps_log: list[str] = []

        # ========== Step 1: 分析项目 ==========
        self._report_progress("deploy", "📋 Step 1/4: 收集项目信息...")
        steps_log.append("📋 Step 1/4: 收集项目信息...")

        parsed = self._parse_github_url(repo_url)
        if not parsed:
            return WorkerResult(success=False, message=f"无效的 GitHub URL: {repo_url}")

        owner, repo = parsed

        self._report_progress("deploy", "  获取 README...")
        readme_result = await self._http.execute(
            "fetch_github_readme",
            {"repo_url": repo_url},
        )
        readme_content = ""
        if readme_result.success and isinstance(readme_result.data, dict):
            readme_content = str(readme_result.data.get("content", ""))

        self._report_progress("deploy", "  获取文件列表...")
        files_result = await self._http.execute(
            "list_github_files",
            {"repo_url": repo_url},
        )
        key_files: list[str] = []
        if files_result.success and isinstance(files_result.data, dict):
            key_files_str = files_result.data.get("key_files", "")
            if isinstance(key_files_str, str) and key_files_str:
                key_files = [f.strip() for f in key_files_str.split(",")]

        steps_log.append(f"  ✓ 仓库: {owner}/{repo}")
        steps_log.append(f"  ✓ 关键文件: {', '.join(key_files[:10]) if key_files else '无'}")

        # ========== Step 2: 克隆仓库 ==========
        self._report_progress("deploy", "📦 Step 2/4: 克隆仓库...")
        steps_log.append("📦 Step 2/4: 克隆仓库...")

        target_dir = os.path.abspath(os.path.expanduser(target_dir))
        clone_path = os.path.join(target_dir, repo)
        safe_target_dir = shlex.quote(target_dir)
        safe_clone_path = shlex.quote(clone_path)
        safe_repo_url = shlex.quote(repo_url)

        if dry_run:
            steps_log.append(f"  [DRY-RUN] 将执行: mkdir -p {target_dir}")
            steps_log.append(f"  [DRY-RUN] 将执行: git clone {repo_url}")
        else:
            mkdir_result = await self._shell.execute(
                "execute_command",
                {"command": f"mkdir -p {safe_target_dir}"},
            )
            if not mkdir_result.success:
                return WorkerResult(
                    success=False,
                    message=f"创建目录失败: {mkdir_result.message}",
                )

            check_result = await self._shell.execute(
                "execute_command",
                {"command": f"test -d {safe_clone_path}"},
            )
            already_exists = False
            marker_handled = False

            if isinstance(check_result.data, dict):
                # 兼容测试桩里仍返回 EXISTS/NOT_EXISTS 的场景
                stdout = check_result.data.get("stdout", "")
                if isinstance(stdout, str):
                    if "EXISTS" in stdout and "NOT" not in stdout:
                        already_exists = True
                        marker_handled = True
                    elif "NOT_EXISTS" in stdout:
                        already_exists = False
                        marker_handled = True

                if not marker_handled:
                    # test -d 约定：目录不存在时 exit_code=1
                    exit_code = check_result.data.get("exit_code")
                    if exit_code == 1:
                        already_exists = False
                        marker_handled = True

            if not marker_handled:
                if check_result.success:
                    already_exists = True
                else:
                    return WorkerResult(
                        success=False,
                        message=f"检查项目目录失败: {check_result.message}",
                    )

            if already_exists:
                steps_log.append(f"  ⚠️ 项目已存在: {clone_path}")

            if not already_exists:
                clone_result = await self._shell.execute(
                    "execute_command",
                    {"command": f"git clone {safe_repo_url} {safe_clone_path}"},
                )
                if not clone_result.success:
                    return WorkerResult(
                        success=False,
                        message=f"克隆失败: {clone_result.message}",
                    )
                steps_log.append(f"  ✓ 克隆完成: {clone_path}")

        # ========== Step 3: LLM 生成部署计划 ==========
        self._report_progress("deploy", "🤖 Step 3/4: AI 分析项目并生成部署计划...")
        steps_log.append("🤖 Step 3/4: AI 分析项目并生成部署计划...")

        self._report_progress("deploy", "  收集本机环境信息...")
        env_info = await self._planner.collect_env_info()
        self._report_progress("deploy", "  调用 LLM 生成部署计划...")
        deploy_steps, project_type, notes, thinking = await self._planner.generate_plan(
            readme=readme_content,
            files=key_files,
            env_info=env_info,
            project_dir=clone_path,
        )

        normalized_steps: list[dict[str, str]] = []
        skipped_empty_commands = 0
        for raw_step in deploy_steps:
            if not isinstance(raw_step, dict):
                continue
            command = raw_step.get("command", "")
            if not isinstance(command, str) or not command.strip():
                skipped_empty_commands += 1
                continue

            command = command.strip()
            description = raw_step.get("description", "")
            if not isinstance(description, str) or not description.strip():
                description = command
            else:
                description = description.strip()

            normalized_steps.append(
                {
                    "description": description,
                    "command": command,
                }
            )

        if not normalized_steps:
            return WorkerResult(
                success=False,
                message="无法生成部署计划：未发现可执行命令（命令为空）。请检查项目结构或手动部署。",
            )
        deploy_steps = normalized_steps

        if skipped_empty_commands > 0:
            self._report_progress(
                "deploy",
                f"  ⚠️ 已跳过 {skipped_empty_commands} 个空命令步骤",
            )
            steps_log.append(f"  ⚠️ 已跳过 {skipped_empty_commands} 个空命令步骤")

        if thinking:
            steps_log.append("  💭 AI 思考过程:")
            for i, thought in enumerate(thinking, 1):
                thought_str = str(thought)
                self._report_progress("deploy", f"    💭 {thought_str}")
                steps_log.append(f"    {i}. {thought_str}")

        steps_log.append(f"  ✓ 项目类型: {project_type}")
        steps_log.append(f"  ✓ 部署步骤: {len(deploy_steps)} 步")
        if notes:
            steps_log.append(f"  📝 备注: {notes}")

        # ========== Step 4: 执行部署计划 ==========
        self._report_progress("deploy", "🚀 Step 4/4: 执行部署计划...")
        steps_log.append("🚀 Step 4/4: 执行部署计划...")

        failed_step: Optional[str] = None
        for i, step in enumerate(deploy_steps, 1):
            description = step.get("description", step.get("command", ""))
            self._report_progress("deploy", f"  [{i}/{len(deploy_steps)}] {description}")
            steps_log.append(f"  [{i}/{len(deploy_steps)}] {description}")

            success, message = await self._executor.execute_with_retry(
                step=step,
                project_dir=clone_path,
                project_type=project_type,
                known_files=key_files,
                dry_run=dry_run,
            )

            if not success:
                failed_step = message
                steps_log.append(f"    ❌ {message}")
                break
            else:
                steps_log.append(f"    {message}")

        # ========== 结果汇总 ==========
        summary = "\n".join(steps_log)

        if failed_step:
            summary += f"\n\n❌ 部署失败: {failed_step}"
            summary += "\n\n💡 可能的解决方法:"
            summary += "\n1. 检查项目 README 了解具体要求"
            summary += "\n2. 手动进入项目目录排查问题"
            summary += f"\n   cd {clone_path}"
            return WorkerResult(
                success=False,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {"project_dir": clone_path, "project_type": project_type, "repo_url": repo_url},
                ),
                message=summary,
                task_completed=True,
                simulated=bool(dry_run),
            )

        # ========== Step 5: 验证部署 ==========
        # 检测是否使用了 Docker 部署（不仅限于 project_type == "docker"）
        uses_docker = any(
            "docker run" in step.get("command", "")
            or "docker compose" in step.get("command", "")
            or "docker-compose" in step.get("command", "")
            for step in deploy_steps
        )

        if uses_docker and not dry_run:
            self._report_progress("deploy", "\n🔍 Step 5/5: 验证部署...")
            (
                verify_success,
                verify_message,
                container_info,
            ) = await self._executor.verify_docker_deployment(
                deploy_steps=deploy_steps,
                project_dir=clone_path,
                project_type=project_type,
                known_files=key_files,
            )

            if not verify_success:
                summary += f"\n\n⚠️ 部署验证失败: {verify_message}"
                summary += "\n\n💡 可能的解决方法:"
                summary += "\n1. 检查 docker logs 查看容器日志"
                summary += "\n2. 确认端口没有被占用"
                summary += "\n3. 检查环境变量是否正确配置"
                summary += f"\n4. 手动进入项目目录排查问题: cd {clone_path}"
                return WorkerResult(
                    success=False,
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {
                            "project_dir": clone_path,
                            "project_type": project_type,
                            "repo_url": repo_url,
                        },
                    ),
                    message=summary,
                    task_completed=True,
                    simulated=bool(dry_run),
                )

            if container_info:
                summary += f"\n\n{verify_message}"

        summary += "\n\n✅ 部署完成！"
        summary += f"\n📂 项目路径: {clone_path}"
        summary += f"\n🎯 项目类型: {project_type}"

        if dry_run:
            summary = "[DRY-RUN 模式]\n\n" + summary

        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {"project_dir": clone_path, "project_type": project_type, "repo_url": repo_url},
            ),
            message=summary,
            task_completed=True,
            simulated=bool(dry_run),
        )
