"""部署工作流节点实现"""

from __future__ import annotations

import os
from typing import Callable, Optional

from src.orchestrator.graph.state import (
    STEP_CLONE,
    STEP_DONE,
    STEP_ERROR,
    STEP_SETUP,
    STEP_START,
    DeployState,
)
from src.workers.deploy import DeployWorker


class DeployNodes:
    """部署工作流节点

    每个节点方法对应 LangGraph 状态图中的一个节点，
    调用 DeployWorker 执行实际操作。
    """

    def __init__(
        self,
        deploy_worker: DeployWorker,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化节点

        Args:
            deploy_worker: DeployWorker 实例
            progress_callback: 进度回调函数
        """
        self._deploy = deploy_worker
        self._progress_callback = progress_callback

    def _report_progress(self, step: str, message: str) -> None:
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(step, message)

    async def analyze_node(self, state: DeployState) -> dict[str, object]:
        """分析节点：获取仓库信息并检测项目类型"""
        self._report_progress("analyze", "🔍 分析仓库结构...")

        repo_url = state.get("repo_url", "")
        if not repo_url:
            return {
                "current_step": STEP_ERROR,
                "error_message": "缺少 repo_url 参数",
            }

        result = await self._deploy.execute(
            "analyze_repo",
            {"repo_url": repo_url},
        )

        steps_completed = list(state.get("steps_completed", []))

        if result.success and result.data:
            project_type = str(result.data.get("project_type", "unknown"))
            key_files_str = str(result.data.get("key_files", ""))
            key_files = [f.strip() for f in key_files_str.split(",") if f.strip()]

            steps_completed.append(f"✅ 分析完成: 项目类型={project_type}")
            self._report_progress("analyze", f"✅ 检测到项目类型: {project_type}")

            return {
                "owner": str(result.data.get("owner", "")),
                "repo": str(result.data.get("repo", "")),
                "project_type": project_type,
                "key_files": key_files,
                "current_step": STEP_CLONE,
                "steps_completed": steps_completed,
            }
        else:
            return {
                "current_step": STEP_ERROR,
                "error_message": result.message,
            }

    async def clone_node(self, state: DeployState) -> dict[str, object]:
        """克隆节点：克隆仓库到目标目录"""
        self._report_progress("clone", "📥 克隆仓库...")

        repo_url = state.get("repo_url", "")
        target_dir = state.get("target_dir", "~/projects")
        dry_run = state.get("dry_run", False)

        result = await self._deploy.execute(
            "clone_repo",
            {
                "repo_url": repo_url,
                "target_dir": target_dir,
                "dry_run": dry_run,
            },
        )

        steps_completed = list(state.get("steps_completed", []))

        if result.success and result.data:
            clone_path = str(result.data.get("path", ""))
            already_exists = result.data.get("already_exists", False)

            if already_exists:
                steps_completed.append(f"⏭️ 仓库已存在: {clone_path}")
                self._report_progress("clone", "⏭️ 仓库已存在，跳过克隆")
            else:
                steps_completed.append(f"✅ 克隆完成: {clone_path}")
                self._report_progress("clone", f"✅ 克隆完成: {clone_path}")

            return {
                "clone_path": clone_path,
                "current_step": STEP_SETUP,
                "steps_completed": steps_completed,
            }
        elif result.simulated:
            # dry-run 模式
            repo = state.get("repo", "")
            clone_path = os.path.join(os.path.expanduser(target_dir), repo)
            steps_completed.append(f"🔸 [DRY-RUN] 将克隆到: {clone_path}")
            self._report_progress("clone", f"🔸 [DRY-RUN] 将克隆到: {clone_path}")

            return {
                "clone_path": clone_path,
                "current_step": STEP_SETUP,
                "steps_completed": steps_completed,
            }
        else:
            return {
                "current_step": STEP_ERROR,
                "error_message": result.message,
            }

    async def setup_node(self, state: DeployState) -> dict[str, object]:
        """环境配置节点：安装依赖、复制配置文件"""
        self._report_progress("setup", "⚙️ 配置环境...")

        clone_path = state.get("clone_path", "")
        project_type = state.get("project_type", "unknown")
        dry_run = state.get("dry_run", False)

        result = await self._deploy.execute(
            "setup_env",
            {
                "project_dir": clone_path,
                "project_type": project_type,
                "dry_run": dry_run,
            },
        )

        steps_completed = list(state.get("steps_completed", []))

        if result.success:
            if result.simulated:
                steps_completed.append("🔸 [DRY-RUN] 将配置环境")
                self._report_progress("setup", "🔸 [DRY-RUN] 环境配置预览完成")
            else:
                steps_completed.append("✅ 环境配置完成")
                self._report_progress("setup", "✅ 环境配置完成")

            return {
                "current_step": STEP_START,
                "steps_completed": steps_completed,
            }
        else:
            return {
                "current_step": STEP_ERROR,
                "error_message": result.message,
            }

    async def start_node(self, state: DeployState) -> dict[str, object]:
        """启动节点：启动服务"""
        self._report_progress("start", "🚀 启动服务...")

        clone_path = state.get("clone_path", "")
        project_type = state.get("project_type", "unknown")
        dry_run = state.get("dry_run", False)

        result = await self._deploy.execute(
            "start_service",
            {
                "project_dir": clone_path,
                "project_type": project_type,
                "dry_run": dry_run,
            },
        )

        steps_completed = list(state.get("steps_completed", []))

        if result.success:
            if result.simulated:
                steps_completed.append("🔸 [DRY-RUN] 将启动服务")
                self._report_progress("start", "🔸 [DRY-RUN] 服务启动预览完成")
            else:
                steps_completed.append("✅ 服务启动成功")
                self._report_progress("start", "✅ 服务启动成功")

            # 构建最终消息
            final_message = self._build_final_message(state, steps_completed)

            return {
                "current_step": STEP_DONE,
                "steps_completed": steps_completed,
                "final_message": final_message,
            }
        else:
            return {
                "current_step": STEP_ERROR,
                "error_message": result.message,
            }

    async def error_node(self, state: DeployState) -> dict[str, object]:
        """错误处理节点"""
        error_message = state.get("error_message", "未知错误")
        self._report_progress("error", f"❌ 部署失败: {error_message}")

        steps_completed = list(state.get("steps_completed", []))
        steps_completed.append(f"❌ 错误: {error_message}")

        return {
            "current_step": STEP_ERROR,
            "steps_completed": steps_completed,
            "final_message": f"部署失败: {error_message}",
        }

    def _build_final_message(
        self,
        state: DeployState,
        steps_completed: list[str],
    ) -> str:
        """构建最终消息"""
        repo_url = state.get("repo_url", "")
        clone_path = state.get("clone_path", "")
        project_type = state.get("project_type", "unknown")

        lines = [
            "## 部署完成 🎉",
            "",
            f"**仓库**: {repo_url}",
            f"**项目类型**: {project_type}",
            f"**部署路径**: {clone_path}",
            "",
            "**执行步骤**:",
        ]
        for step in steps_completed:
            lines.append(f"  {step}")

        return "\n".join(lines)
