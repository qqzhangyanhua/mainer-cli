"""ReAct 循环引擎"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from src.config.manager import OpsAIConfig
from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient

from src.orchestrator.graph_adapter import build_graph_messages, parse_graph_messages
from src.orchestrator.graph.react_state import ReactState
from src.types import ConversationEntry, Instruction, RiskLevel, WorkerResult
from src.workers.audit import AuditWorker
from src.workers.base import BaseWorker
from src.workers.system import SystemWorker


class OrchestratorEngine:
    """Orchestrator 引擎

    统一使用 LangGraph 实现 ReAct (Reason-Act) 循环：
    preprocess → reason → safety → [approve?] → execute → check → [loop/end]
    """

    def __init__(
        self,
        config: OpsAIConfig,
        confirmation_callback: Optional[
            Callable[[Instruction, RiskLevel], bool | Awaitable[bool]]
        ] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        use_sqlite_checkpoint: bool = False,
    ) -> None:
        """初始化引擎

        Args:
            config: 配置对象
            confirmation_callback: 确认回调函数，用于高危操作确认
            dry_run: 是否启用 dry-run 模式
            progress_callback: 进度回调函数，接收 (step_name, message) 用于实时显示进度
            use_sqlite_checkpoint: 是否使用 SQLite 持久化检查点
        """
        self._config = config
        self._llm_client = LLMClient(config.llm)
        self._context = EnvironmentContext()
        self._confirmation_callback = confirmation_callback
        self._dry_run = dry_run or config.safety.dry_run_by_default
        self._progress_callback = progress_callback

        audit_log_path = Path(self._config.audit.log_path).expanduser()

        # 初始化 Workers
        self._workers: dict[str, BaseWorker] = {
            "system": SystemWorker(),
            "audit": AuditWorker(
                log_path=audit_log_path,
                max_log_size_mb=self._config.audit.max_log_size_mb,
                retain_days=self._config.audit.retain_days,
            ),
        }

        # 注册 ChatWorker
        try:
            from src.workers.chat import ChatWorker

            self._workers["chat"] = ChatWorker()
        except ImportError:
            pass

        # 注册 ShellWorker
        try:
            from src.workers.shell import ShellWorker

            self._workers["shell"] = ShellWorker()
        except ImportError:
            pass

        # 尝试导入并注册 ContainerWorker
        try:
            from src.workers.container import ContainerWorker

            self._workers["container"] = ContainerWorker()
        except ImportError:
            pass

        # 注册 AnalyzeWorker（需要 LLM 客户端）
        try:
            from src.workers.analyze import AnalyzeWorker

            self._workers["analyze"] = AnalyzeWorker(self._llm_client)
        except ImportError:
            pass

        # 注册 HttpWorker
        try:
            from src.workers.http import HttpWorker

            self._workers["http"] = HttpWorker(self._config.http)
        except ImportError:
            pass

        # 注册 GitWorker
        try:
            from src.workers.git import GitWorker

            self._workers["git"] = GitWorker()
        except ImportError:
            pass

        # 注册 DeployWorker（需要 HttpWorker、ShellWorker 和 LLMClient）
        http_worker = self._workers.get("http")
        shell_worker = self._workers.get("shell")
        if http_worker and shell_worker:
            try:
                from src.workers.deploy import DeployWorker
                from src.workers.http import HttpWorker as HttpWorkerType
                from src.workers.shell import ShellWorker as ShellWorkerType

                if isinstance(http_worker, HttpWorkerType) and isinstance(
                    shell_worker, ShellWorkerType
                ):
                    # 创建适配器：将 DeployWorker 的确认回调适配到 Engine 的确认回调
                    deploy_confirmation_callback = None
                    deploy_ask_user_callback = None

                    if confirmation_callback is not None:
                        deploy_confirmation_callback = self._create_deploy_confirmation_adapter(
                            confirmation_callback
                        )

                    self._workers["deploy"] = DeployWorker(
                        http_worker,
                        shell_worker,
                        self._llm_client,
                        progress_callback,
                        deploy_confirmation_callback,
                        deploy_ask_user_callback,
                    )
            except ImportError:
                pass

        # 始终初始化 ReactGraph
        from src.orchestrator.graph import ReactGraph

        enable_interrupts = confirmation_callback is not None
        self._react_graph: ReactGraph = ReactGraph(
            llm_client=self._llm_client,
            workers=self._workers,
            context=self._context,
            dry_run=self._dry_run,
            max_risk=self._config.safety.tui_max_risk,
            auto_approve_safe=self._config.safety.auto_approve_safe,
            require_dry_run_for_high_risk=self._config.safety.require_dry_run_for_high_risk,
            enable_checkpoints=True,
            enable_interrupts=enable_interrupts,
            use_sqlite=use_sqlite_checkpoint,
            checkpoint_db_path=None,
            progress_callback=progress_callback,
        )

    def get_worker(self, name: str) -> Optional[BaseWorker]:
        """获取 Worker

        Args:
            name: Worker 名称

        Returns:
            Worker 实例，不存在返回 None
        """
        return self._workers.get(name)

    def _create_deploy_confirmation_adapter(
        self,
        confirmation_callback: Callable[[Instruction, RiskLevel], bool | Awaitable[bool]],
    ) -> Callable[[str, str], Awaitable[bool]]:
        """创建 DeployWorker 确认回调的适配器

        将 DeployWorker 的 (action, detail) 格式转换为 Engine 的 (Instruction, RiskLevel) 格式
        """

        async def adapter(action: str, detail: str) -> bool:
            instruction = Instruction(
                worker="deploy",
                action="自主修复",
                args={"operation": action, "detail": detail},
                risk_level="medium",
            )
            result = confirmation_callback(instruction, "medium")
            if inspect.isawaitable(result):
                return await result
            return bool(result)

        return adapter

    async def execute_instruction(self, instruction: Instruction) -> WorkerResult:
        """执行指令

        Args:
            instruction: 待执行的指令

        Returns:
            执行结果
        """
        worker = self.get_worker(instruction.worker)
        if worker is None:
            return WorkerResult(
                success=False,
                message=f"Unknown worker: {instruction.worker}",
            )

        # 如果全局启用了 dry_run，则注入到参数中
        args = instruction.args.copy()
        if self._dry_run or instruction.dry_run:
            args["dry_run"] = True

        return await worker.execute(instruction.action, args)

    def _build_graph_messages(
        self, history: Optional[list[ConversationEntry]]
    ) -> list[dict[str, object]]:
        """将 ConversationEntry 转换为 LangGraph 消息格式（委托到 graph_adapter）"""
        return build_graph_messages(history)

    def _parse_graph_messages(
        self, messages: list[dict[str, str]]
    ) -> list[ConversationEntry]:
        """从 LangGraph 消息历史解析 ConversationEntry（委托到 graph_adapter）"""
        return parse_graph_messages(messages)

    async def react_loop_graph(
        self,
        user_input: str,
        max_iterations: int = 5,
        session_id: Optional[str] = None,
        session_history: Optional[list[ConversationEntry]] = None,
    ) -> str:
        """执行 ReAct 循环（LangGraph 版本）

        Args:
            user_input: 用户输入
            max_iterations: 最大迭代次数
            session_id: 会话 ID（用于持久化和恢复）
            session_history: 会话级对话历史

        Returns:
            最终结果消息
        """
        try:
            messages = self._build_graph_messages(session_history)
            final_state = await self._react_graph.run(
                user_input=user_input,
                session_id=session_id,
                max_iterations=max_iterations,
                messages=messages,
            )

            # 检查是否被中断（需要审批）
            if final_state.get("needs_approval") and not final_state.get("approval_granted"):
                return "__APPROVAL_REQUIRED__"

            # 更新会话历史
            if session_history is not None:
                parsed = self._parse_graph_messages(final_state.get("messages", []))
                session_history.clear()
                session_history.extend(parsed)

            return final_state.get("final_message", "Task completed")
        except Exception as e:
            return f"Error in ReactGraph: {e}"

    async def resume_react_loop(
        self,
        session_id: str,
        approval_granted: bool = True,
        session_history: Optional[list[ConversationEntry]] = None,
    ) -> str:
        """恢复被中断的 ReAct 循环（审批后继续）

        Args:
            session_id: 会话 ID
            approval_granted: 审批是否通过
            session_history: 会话级对话历史

        Returns:
            最终结果消息
        """
        try:
            final_state = await self._react_graph.resume(
                session_id=session_id,
                approval_granted=approval_granted,
            )

            if final_state.get("needs_approval") and not final_state.get("approval_granted"):
                return "__APPROVAL_REQUIRED__"

            # 更新会话历史
            if session_history is not None:
                parsed = self._parse_graph_messages(final_state.get("messages", []))
                session_history.clear()
                session_history.extend(parsed)

            return final_state.get("final_message", "Task completed")
        except Exception as e:
            return f"Error resuming ReactGraph: {e}"

    def get_graph_state(self, session_id: str) -> Optional[ReactState]:
        """获取 LangGraph 会话状态

        Args:
            session_id: 会话 ID

        Returns:
            当前状态，不存在返回 None
        """
        return self._react_graph.get_state(session_id)

    def get_mermaid_diagram(self) -> str:
        """获取 ReAct 工作流的 Mermaid 图表

        Returns:
            Mermaid 图表字符串
        """
        return self._react_graph.get_mermaid_diagram()
