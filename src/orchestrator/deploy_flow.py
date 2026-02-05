"""部署流程控制 - 生成下一步指令"""

from __future__ import annotations

from typing import Optional

from src.types import ConversationEntry, Instruction


def _extract_deploy_context(
    history: list[ConversationEntry],
    user_input: str,
) -> tuple[Optional[str], Optional[str]]:
    """从历史中提取部署上下文（project_type/clone_path）"""
    project_type: Optional[str] = None
    clone_path: Optional[str] = None

    for entry in history:
        if entry.user_input != user_input:
            continue
        if entry.instruction.worker != "deploy":
            continue

        data = entry.result.data
        if not isinstance(data, dict):
            continue

        action = entry.instruction.action
        if action == "analyze_repo":
            pt = data.get("project_type")
            if isinstance(pt, str) and pt:
                project_type = pt
        elif action == "clone_repo":
            path = data.get("path")
            if isinstance(path, str) and path:
                clone_path = path
        elif action in {"setup_env", "start_service"}:
            if not clone_path:
                path = data.get("project_dir")
                if isinstance(path, str) and path:
                    clone_path = path
            if not project_type:
                pt = data.get("project_type")
                if isinstance(pt, str) and pt:
                    project_type = pt

    return project_type, clone_path


def next_deploy_instruction(
    repo_url: str,
    history: list[ConversationEntry],
    user_input: str,
    target_dir: str = "~/projects",
) -> tuple[Optional[Instruction], str]:
    """根据历史生成下一步部署指令"""
    last_action: Optional[str] = None
    for entry in reversed(history):
        if entry.user_input != user_input:
            continue
        if entry.instruction.worker != "deploy":
            continue
        last_action = entry.instruction.action
        break

    if last_action is None:
        return (
            Instruction(
                worker="deploy",
                action="analyze_repo",
                args={"repo_url": repo_url},
                risk_level="safe",
            ),
            "",
        )

    if last_action == "analyze_repo":
        return (
            Instruction(
                worker="deploy",
                action="clone_repo",
                args={"repo_url": repo_url, "target_dir": target_dir},
                risk_level="medium",
            ),
            "",
        )

    project_type, clone_path = _extract_deploy_context(history, user_input)

    if last_action == "clone_repo":
        if not project_type or not clone_path:
            return None, "缺少部署上下文：需要项目类型与克隆路径"
        return (
            Instruction(
                worker="deploy",
                action="setup_env",
                args={"project_dir": clone_path, "project_type": project_type},
                risk_level="medium",
            ),
            "",
        )

    if last_action == "setup_env":
        if not project_type or not clone_path:
            return None, "缺少部署上下文：需要项目类型与项目路径"
        return (
            Instruction(
                worker="deploy",
                action="start_service",
                args={"project_dir": clone_path, "project_type": project_type},
                risk_level="medium",
            ),
            "",
        )

    if last_action == "start_service":
        return None, "部署流程已完成"

    return None, f"未知部署步骤: {last_action}"
