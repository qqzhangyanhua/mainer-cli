"""ReAct 循环 LangGraph 状态图"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal, Optional, Union

from langgraph.graph import END, START, StateGraph

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.graph.checkpoint import get_checkpoint_saver
from src.orchestrator.graph.react_nodes import ReactNodes
from src.orchestrator.graph.react_state import ReactState
from src.types import RiskLevel
from src.workers.base import BaseWorker


def route_after_safety(
    state: ReactState,
) -> Literal["approve", "execute", "error"]:
    """安全检查后的路由决策"""
    if state.get("is_error", False):
        return "error"
    if state.get("needs_approval", False):
        return "approve"
    return "execute"


def route_after_approve(
    state: ReactState,
) -> Literal["execute", "error"]:
    """审批后的路由决策"""
    if state.get("approval_granted", False):
        return "execute"
    return "error"  # 拒绝则进入错误节点


def route_after_check(
    state: ReactState,
) -> Literal["reason", "end", "error"]:
    """检查后的路由决策"""
    if state.get("is_error", False):
        return "error"
    if state.get("task_completed", False):
        return "end"
    return "reason"  # 继续下一轮迭代


class ReactGraph:
    """ReAct 循环 LangGraph 封装

    实现完整的 ReAct 工作流：
    preprocess → reason → safety → [approve?] → execute → check → [loop/end]
    """

    def __init__(
        self,
        llm_client: LLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
        dry_run: bool = False,
        max_risk: RiskLevel = "high",
        auto_approve_safe: bool = True,
        require_dry_run_for_high_risk: bool = True,
        enable_checkpoints: bool = True,
        enable_interrupts: bool = True,
        use_sqlite: bool = False,
        checkpoint_db_path: Union[str, Path, None] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化 ReAct Graph

        Args:
            llm_client: LLM 客户端
            workers: Worker 实例字典
            context: 环境上下文
            dry_run: 是否启用 dry-run 模式
            max_risk: 最大允许风险等级
            auto_approve_safe: safe 操作是否自动通过
            require_dry_run_for_high_risk: 高风险操作是否强制 dry-run
            enable_checkpoints: 是否启用状态持久化
            enable_interrupts: 是否启用 interrupt 机制（用于人工确认）
            use_sqlite: 是否使用 SQLite 持久化（默认使用内存存储）
            checkpoint_db_path: SQLite 数据库路径（仅当 use_sqlite=True 时有效）
            progress_callback: 进度回调函数
        """
        self._llm = llm_client
        self._workers = workers
        self._context = context
        self._dry_run = dry_run
        self._enable_interrupts = enable_interrupts
        self._progress_callback = progress_callback

        self._nodes = ReactNodes(
            llm_client=llm_client,
            workers=workers,
            context=context,
            dry_run=dry_run,
            max_risk=max_risk,
            auto_approve_safe=auto_approve_safe,
            require_dry_run_for_high_risk=require_dry_run_for_high_risk,
            progress_callback=progress_callback,
        )

        # 构建状态图
        self._graph = self._build_graph(
            enable_checkpoints=enable_checkpoints,
            enable_interrupts=enable_interrupts,
            use_sqlite=use_sqlite,
            checkpoint_db_path=checkpoint_db_path,
        )

    def _build_graph(
        self,
        enable_checkpoints: bool,
        enable_interrupts: bool,
        use_sqlite: bool,
        checkpoint_db_path: Union[str, Path, None],
    ) -> StateGraph:
        """构建状态图"""
        builder: StateGraph[ReactState] = StateGraph(ReactState)

        # 添加节点
        builder.add_node("preprocess", self._nodes.preprocess_node)
        builder.add_node("reason", self._nodes.reason_node)
        builder.add_node("safety", self._nodes.safety_node)
        builder.add_node("approve", self._nodes.approve_node)
        builder.add_node("execute", self._nodes.execute_node)
        builder.add_node("check", self._nodes.check_node)
        builder.add_node("error", self._nodes.error_node)

        # 添加边
        builder.add_edge(START, "preprocess")
        builder.add_edge("preprocess", "reason")
        builder.add_edge("reason", "safety")

        # 条件边：安全检查后
        builder.add_conditional_edges(
            "safety",
            route_after_safety,
            {
                "approve": "approve",
                "execute": "execute",
                "error": "error",
            },
        )

        # 条件边：审批后
        builder.add_conditional_edges(
            "approve",
            route_after_approve,
            {
                "execute": "execute",
                "error": "error",
            },
        )

        # execute 后检查
        builder.add_edge("execute", "check")

        # 条件边：检查后
        builder.add_conditional_edges(
            "check",
            route_after_check,
            {
                "reason": "reason",  # 继续下一轮
                "end": END,
                "error": "error",
            },
        )

        # error 节点结束
        builder.add_edge("error", END)

        # 编译
        if enable_checkpoints:
            checkpointer = get_checkpoint_saver(
                use_sqlite=use_sqlite,
                db_path=checkpoint_db_path,
            )
            if enable_interrupts:
                # 在 approve 节点前中断，等待用户确认
                return builder.compile(
                    checkpointer=checkpointer,
                    interrupt_before=["approve"],
                )
            else:
                return builder.compile(checkpointer=checkpointer)
        else:
            return builder.compile()

    async def run(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        messages: Optional[list[dict[str, object]]] = None,
    ) -> ReactState:
        """执行 ReAct 循环

        Args:
            user_input: 用户输入
            session_id: 会话 ID（用于持久化）
            max_iterations: 最大迭代次数

        Returns:
            最终状态
        """
        initial_state: ReactState = {
            "user_input": user_input,
            "session_id": session_id or "default",
            "messages": messages or [],
            "iteration": 0,
            "max_iterations": max_iterations,
            "task_completed": False,
            "needs_approval": False,
            "approval_granted": False,
            "is_error": False,
        }

        config = {"configurable": {"thread_id": session_id or "default"}}

        # 执行状态图
        final_state = await self._graph.ainvoke(initial_state, config)

        return final_state

    async def resume(
        self,
        session_id: str,
        approval_granted: bool = True,
    ) -> ReactState:
        """恢复被中断的会话（用于审批后继续）

        Args:
            session_id: 会话 ID
            approval_granted: 审批是否通过

        Returns:
            最终状态
        """
        config = {"configurable": {"thread_id": session_id}}

        # 更新状态：设置审批结果
        self._graph.update_state(
            config,
            {"approval_granted": approval_granted},
        )

        # 继续执行
        final_state = await self._graph.ainvoke(None, config)

        return final_state

    def get_state(self, session_id: str) -> Optional[ReactState]:
        """获取会话状态

        Args:
            session_id: 会话 ID

        Returns:
            当前状态，不存在返回 None
        """
        config = {"configurable": {"thread_id": session_id}}
        try:
            state_snapshot = self._graph.get_state(config)
            return state_snapshot.values  # type: ignore[return-value]
        except Exception:
            return None

    def get_state_history(self, session_id: str) -> list[ReactState]:
        """获取会话状态历史

        Args:
            session_id: 会话 ID

        Returns:
            状态历史列表
        """
        config = {"configurable": {"thread_id": session_id}}
        history = []
        for state_snapshot in self._graph.get_state_history(config):
            history.append(state_snapshot.values)  # type: ignore[arg-type]
        return history

    def get_mermaid_diagram(self) -> str:
        """获取 Mermaid 格式的状态图

        Returns:
            Mermaid 图表字符串
        """
        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception as e:
            return f"Failed to generate diagram: {e}"
