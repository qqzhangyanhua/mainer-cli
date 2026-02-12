"""部署工作流 LangGraph 状态图"""

from __future__ import annotations

import os
from typing import Callable, Literal, Optional

from langgraph.graph import END, START, StateGraph

from src.orchestrator.graph.nodes import DeployNodes
from src.orchestrator.graph.state import (
    STEP_ERROR,
    DeployState,
)
from src.workers.deploy import DeployWorker


def route_after_analyze(state: DeployState) -> Literal["clone", "error"]:
    """分析后路由决策"""
    if state.get("current_step") == STEP_ERROR:
        return "error"
    if state.get("project_type") == "unknown":
        # 未知项目类型，仍然尝试克隆
        return "clone"
    return "clone"


def route_after_clone(state: DeployState) -> Literal["setup", "error"]:
    """克隆后路由决策"""
    if state.get("current_step") == STEP_ERROR:
        return "error"
    return "setup"


def route_after_setup(state: DeployState) -> Literal["start", "end", "error"]:
    """环境配置后路由决策"""
    if state.get("current_step") == STEP_ERROR:
        return "error"

    project_type = state.get("project_type", "unknown")

    # 这些项目类型需要启动服务
    need_start = ["docker", "nodejs", "python", "go", "rust"]
    if project_type in need_start:
        return "start"

    # 其他类型（如静态网站）不需要启动
    return "end"


class DeployGraph:
    """部署工作流 LangGraph 封装

    提供完整的 GitHub 项目部署流程：
    analyze → clone → setup → start
    """

    def __init__(
        self,
        deploy_worker: DeployWorker,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化部署工作流

        Args:
            deploy_worker: DeployWorker 实例
            progress_callback: 进度回调函数
        """
        self._deploy_worker = deploy_worker
        self._progress_callback = progress_callback
        self._nodes = DeployNodes(deploy_worker, progress_callback)
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建状态图"""
        builder: StateGraph[DeployState] = StateGraph(DeployState)

        # 添加节点
        builder.add_node("analyze", self._nodes.analyze_node)
        builder.add_node("clone", self._nodes.clone_node)
        builder.add_node("setup", self._nodes.setup_node)
        builder.add_node("start", self._nodes.start_node)
        builder.add_node("error", self._nodes.error_node)

        # 添加边
        builder.add_edge(START, "analyze")

        # 条件边：analyze 之后
        builder.add_conditional_edges(
            "analyze",
            route_after_analyze,
            {
                "clone": "clone",
                "error": "error",
            },
        )

        # 条件边：clone 之后
        builder.add_conditional_edges(
            "clone",
            route_after_clone,
            {
                "setup": "setup",
                "error": "error",
            },
        )

        # 条件边：setup 之后
        builder.add_conditional_edges(
            "setup",
            route_after_setup,
            {
                "start": "start",
                "end": END,
                "error": "error",
            },
        )

        # start 和 error 都结束
        builder.add_edge("start", END)
        builder.add_edge("error", END)

        return builder.compile()

    async def run(
        self,
        repo_url: str,
        target_dir: Optional[str] = None,
        dry_run: bool = False,
    ) -> DeployState:
        """执行部署工作流

        Args:
            repo_url: GitHub 仓库 URL
            target_dir: 部署目标目录
            dry_run: 是否为模拟执行

        Returns:
            最终状态
        """
        resolved_target_dir = target_dir if target_dir and target_dir.strip() else os.getcwd()
        initial_state: DeployState = {
            "repo_url": repo_url,
            "target_dir": resolved_target_dir,
            "dry_run": dry_run,
            "steps_completed": [],
            "current_step": "analyze",
        }

        # 执行状态图
        final_state = await self._graph.ainvoke(initial_state)

        return final_state

    def get_mermaid_diagram(self) -> str:
        """获取 Mermaid 格式的状态图

        Returns:
            Mermaid 图表字符串
        """
        return self._graph.get_graph().draw_mermaid()
