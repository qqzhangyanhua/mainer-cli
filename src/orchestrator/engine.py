"""ReAct 循环引擎"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Optional

from typing import TYPE_CHECKING

from src.config.manager import OpsAIConfig
from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient

from src.orchestrator.error_helper import ErrorHelper
from src.orchestrator.graph_adapter import build_graph_messages, parse_graph_messages
from src.orchestrator.instruction import (
    available_workers_text,
    build_fallback_instruction,
    generate_instruction_with_retry,
)
from src.orchestrator.preprocessor import RequestPreprocessor
from src.orchestrator.prompt import PromptBuilder
from src.orchestrator.safety import check_safety
from src.orchestrator.validation import validate_instruction
from src.types import ConversationEntry, Instruction, RiskLevel, WorkerResult
from src.workers.audit import AuditWorker
from src.workers.base import BaseWorker
from src.workers.system import SystemWorker

if TYPE_CHECKING:
    from src.orchestrator.graph import ReactGraph


class OrchestratorEngine:
    """Orchestrator 引擎

    实现 ReAct (Reason-Act) 循环：
    1. Reason: LLM 生成下一步指令
    2. Safety Check: 检查安全级别
    3. Act: 执行 Worker
    4. 判断是否完成
    """

    def __init__(
        self,
        config: OpsAIConfig,
        confirmation_callback: Optional[
            Callable[[Instruction, RiskLevel], bool | Awaitable[bool]]
        ] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        use_langgraph: bool = False,
        use_sqlite_checkpoint: bool = False,
    ) -> None:
        """初始化引擎

        Args:
            config: 配置对象
            confirmation_callback: 确认回调函数，用于高危操作确认
            dry_run: 是否启用 dry-run 模式
            progress_callback: 进度回调函数，接收 (step_name, message) 用于实时显示进度
            use_langgraph: 是否使用 LangGraph 模式（默认 False，保持向后兼容）
            use_sqlite_checkpoint: 是否使用 SQLite 持久化检查点（仅当 use_langgraph=True 时有效）
        """
        self._config = config
        self._llm_client = LLMClient(config.llm)
        self._prompt_builder = PromptBuilder()
        self._preprocessor = RequestPreprocessor()
        self._error_helper = ErrorHelper()
        self._context = EnvironmentContext()
        self._confirmation_callback = confirmation_callback
        self._dry_run = dry_run or config.safety.dry_run_by_default
        self._progress_callback = progress_callback
        self._use_langgraph = use_langgraph

        # 初始化 Workers
        self._workers: dict[str, BaseWorker] = {
            "system": SystemWorker(),
            "audit": AuditWorker(),
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
                        # ask_user_callback 需要从外部注入，先设为 None
                        # DeployWorker 支持后续通过 set_ask_user_callback 注入

                    self._workers["deploy"] = DeployWorker(
                        http_worker,
                        shell_worker,
                        self._llm_client,  # 传递 LLM 客户端实现智能部署
                        progress_callback,  # 传递进度回调
                        deploy_confirmation_callback,  # 传递确认回调（适配器）
                        deploy_ask_user_callback,  # 用户选择回调（后续注入）
                    )
            except ImportError:
                pass

        # 初始化 ReactGraph（如果启用）
        self._react_graph: Optional["ReactGraph"] = None
        if self._use_langgraph:
            from src.orchestrator.graph import ReactGraph

            # 判断是否启用 interrupt（TUI 模式才需要）
            enable_interrupts = confirmation_callback is not None
            self._react_graph = ReactGraph(
                llm_client=self._llm_client,
                workers=self._workers,
                context=self._context,
                dry_run=self._dry_run,
                enable_checkpoints=True,
                enable_interrupts=enable_interrupts,
                use_sqlite=use_sqlite_checkpoint,
                checkpoint_db_path=None,  # 使用默认路径
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
            # 创建一个虚拟的 Instruction 用于确认对话框
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

    def _get_list_command(self, target_type: str) -> str:
        """根据目标类型返回列表命令

        Args:
            target_type: 对象类型（docker、process、port 等）

        Returns:
            对应的列表命令
        """
        commands = {
            "docker": "docker ps",
            "process": "ps aux",
            "port": "ss -tlnp",
            "file": "ls -la",
            "systemd": "systemctl list-units --type=service --state=running",
            "network": "ip addr",
        }
        return commands.get(target_type, "docker ps")

    def _available_workers_text(self) -> str:
        """构建可用 Worker/Action 列表文本"""
        return available_workers_text(self._workers)

    def _build_instruction(self, parsed: dict[str, object]) -> Instruction:
        """从解析后的 JSON 构建指令，带基础容错（委托到 instruction 模块）"""
        from src.orchestrator.instruction import build_instruction
        return build_instruction(parsed)

    def _build_fallback_instruction(
        self, user_input: str, error_message: str
    ) -> Optional[Instruction]:
        """构建兜底指令（委托到 instruction 模块）"""
        return build_fallback_instruction(user_input, error_message, self._workers)

    def _parse_and_validate_instruction(self, response: str) -> tuple[Optional[Instruction], str]:
        """解析并校验 LLM 指令（委托到 instruction 模块）"""
        from src.orchestrator.instruction import parse_and_validate_instruction
        return parse_and_validate_instruction(response, self._llm_client, self._workers)

    def _build_repair_prompt(self, user_input: str, error_message: str) -> str:
        """构建修复提示（委托到 instruction 模块）"""
        from src.orchestrator.instruction import build_repair_prompt
        return build_repair_prompt(user_input, error_message, self._workers)

    async def _generate_instruction_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        user_input: str,
        history: Optional[list[ConversationEntry]],
    ) -> tuple[Optional[Instruction], str]:
        """生成指令并进行一次纠错重试（委托到 instruction 模块）"""
        return await generate_instruction_with_retry(
            self._llm_client, self._workers,
            system_prompt, user_prompt, user_input, history,
        )

    def _build_graph_messages(
        self, history: Optional[list[ConversationEntry]]
    ) -> list[dict[str, object]]:
        """将 ConversationEntry 转换为 LangGraph 消息格式（委托到 graph_adapter）"""
        return build_graph_messages(history)

    def _parse_graph_messages(self, messages: list[object]) -> list[ConversationEntry]:
        """从 LangGraph 消息历史解析 ConversationEntry（委托到 graph_adapter）"""
        return parse_graph_messages(messages)

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

    async def react_loop(
        self,
        user_input: str,
        max_iterations: int = 5,
        session_history: Optional[list[ConversationEntry]] = None,
    ) -> str:
        """执行 ReAct 循环

        Args:
            user_input: 用户输入
            max_iterations: 最大迭代次数，防止死循环
            session_history: 会话级对话历史（跨轮次保持）

        Returns:
            最终结果消息
        """
        # 使用传入的会话历史，或创建新的
        # 注意：必须保持引用，不能用 `or []`（空列表被视为 falsy）
        conversation_history: list[ConversationEntry] = (
            session_history if session_history is not None else []
        )

        for iteration in range(max_iterations):
            # 0. 预处理：意图检测 + 指代解析
            preprocessed = self._preprocessor.preprocess(user_input, conversation_history)

            # 高置信度的解释意图 - 直接生成 Instruction，绕过 LLM
            if preprocessed.intent == "identity":
                chat_worker = self.get_worker("chat")
                if chat_worker and "respond" in chat_worker.get_capabilities():
                    if self._progress_callback:
                        self._progress_callback("preprocessing", "👋 Detected: identity request")

                    instruction = Instruction(
                        worker="chat",
                        action="respond",
                        args={
                            "message": (
                                "我是一个运维助手，可以帮你排查问题、部署项目、查看日志、"
                                "执行常用命令并解释输出。告诉我你的需求即可。"
                            )
                        },
                        risk_level="safe",
                    )
                else:
                    # 无 chat worker，回退到普通流程
                    if self._progress_callback:
                        self._progress_callback("reasoning", "🤔 Analyzing your request...")

                    system_prompt = self._prompt_builder.build_system_prompt(
                        self._context,
                        available_workers=self._workers,
                    )
                    user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

                    instruction, error = await self._generate_instruction_with_retry(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        user_input=user_input,
                        history=conversation_history,
                    )
                    if instruction is None:
                        return f"Error: {error}"
            elif (
                preprocessed.confidence == "high"
                and preprocessed.intent == "explain"
                and preprocessed.resolved_target
            ):
                if self._progress_callback:
                    target = preprocessed.resolved_target
                    ttype = preprocessed.target_type
                    self._progress_callback(
                        "preprocessing",
                        f"🎯 Detected: explain '{target}' ({ttype})",
                    )

                instruction = Instruction(
                    worker="analyze",
                    action="explain",
                    args={
                        "target": preprocessed.resolved_target,
                        "type": preprocessed.target_type or "docker",
                    },
                    risk_level="safe",
                )
                # 跳过 LLM 推理，直接执行
            elif (
                preprocessed.intent == "explain"
                and preprocessed.needs_context
                and preprocessed.target_type
            ):
                # 需要先获取上下文再分析
                # 根据类型生成列表命令
                if self._progress_callback:
                    self._progress_callback(
                        "preprocessing",
                        f"🔍 Need context for {preprocessed.target_type}, fetching list first...",
                    )

                list_command = self._get_list_command(preprocessed.target_type)
                instruction = Instruction(
                    worker="shell",
                    action="execute_command",
                    args={"command": list_command},
                    risk_level="safe",
                )
                # task_completed 默认为 False，循环会继续
            elif preprocessed.intent == "deploy":
                # deploy 意图 - 直接使用一键部署，无需分步
                repo_url = self._preprocessor.extract_repo_url(user_input)
                if repo_url and self.get_worker("deploy"):
                    if self._progress_callback:
                        self._progress_callback(
                            "preprocessing", f"🚀 Deploy intent detected for: {repo_url}"
                        )

                    # 直接生成一键部署指令，不再使用分步流程
                    instruction = Instruction(
                        worker="deploy",
                        action="deploy",
                        args={"repo_url": repo_url, "target_dir": "~/projects"},
                        risk_level="medium",
                    )
                else:
                    # 无法提取 URL 或缺少 deploy worker，回退到普通处理
                    if self._progress_callback:
                        self._progress_callback("reasoning", "🤔 Analyzing your request...")

                    system_prompt = self._prompt_builder.build_system_prompt(
                        self._context,
                        available_workers=self._workers,
                    )
                    user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

                    instruction, error = await self._generate_instruction_with_retry(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        user_input=user_input,
                        history=conversation_history,
                    )
                    if instruction is None:
                        return f"Error: {error}"
            else:
                # 1. Reason: LLM 生成下一步指令
                if self._progress_callback:
                    self._progress_callback("reasoning", "🤔 Analyzing your request...")

                system_prompt = self._prompt_builder.build_system_prompt(
                    self._context,
                    available_workers=self._workers,
                )
                # 不再在 user_prompt 中嵌入历史，改用 LLM 标准多轮对话格式
                user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

                instruction, error = await self._generate_instruction_with_retry(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_input=user_input,
                    history=conversation_history,
                )
                if instruction is None:
                    return f"Error: {error}"

            # 指令校验（防止未知 Worker/Action）
            valid, error = validate_instruction(instruction, self._workers)
            if not valid:
                fallback = self._build_fallback_instruction(user_input, error)
                if fallback:
                    instruction = fallback
                else:
                    return f"Error: {error}"

            # 显示生成的指令
            if self._progress_callback:
                worker_action = f"{instruction.worker}.{instruction.action}"
                self._progress_callback(
                    "instruction",
                    f"📋 Instruction: {worker_action}(args={instruction.args})",
                )

            # 2. Safety Check
            risk = check_safety(instruction)
            if self._progress_callback:
                risk_emoji = {"safe": "✅", "medium": "⚠️", "high": "🚨"}.get(risk, "❓")
                self._progress_callback("safety", f"{risk_emoji} Risk level: {risk}")
            if risk in ["medium", "high"]:
                if self._confirmation_callback:
                    confirmed = self._confirmation_callback(instruction, risk)
                    if inspect.isawaitable(confirmed):
                        confirmed = await confirmed
                    if not confirmed:
                        # 记录拒绝
                        await self._log_operation(
                            user_input,
                            instruction,
                            risk,
                            confirmed=False,
                            exit_code=-1,
                            output="Rejected by user",
                        )
                        return "Operation cancelled by user"
                else:
                    # CLI 模式无确认回调，自动拒绝
                    return (
                        f"Error: {risk.upper()}-risk operation requires TUI mode for confirmation"
                    )

            # 3. Act: 执行 Worker
            if self._progress_callback:
                self._progress_callback(
                    "executing", f"⚙️  Executing {instruction.worker}.{instruction.action}..."
                )

            result = await self.execute_instruction(instruction)

            # 如果失败，增强错误消息
            if not result.success:
                result = self._error_helper.enhance_error_message(result, user_input)

            if self._progress_callback:
                status_emoji = "✅" if result.success else "❌"
                self._progress_callback("result", f"{status_emoji} {result.message}")

            # 4. 记录到审计日志
            await self._log_operation(
                user_input,
                instruction,
                risk,
                confirmed=True,
                exit_code=0 if result.success else 1,
                output=result.message,
            )

            # 5. 记录历史（包含用户原始输入）
            conversation_history.append(
                ConversationEntry(
                    instruction=instruction,
                    result=result,
                    user_input=user_input,
                )
            )

            # 6. 判断是否完成
            if result.task_completed:
                return result.message

        return "Task incomplete: reached maximum iterations"

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

        Returns:
            最终结果消息
        """
        if self._react_graph is None:
            return "Error: LangGraph mode not enabled. Set use_langgraph=True in constructor."

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
                # 返回特殊消息，TUI 可以据此判断需要调用 resume_react_loop
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

        Returns:
            最终结果消息
        """
        if self._react_graph is None:
            return "Error: LangGraph mode not enabled"

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

    def get_graph_state(self, session_id: str) -> Optional[dict[str, object]]:
        """获取 LangGraph 会话状态

        Args:
            session_id: 会话 ID

        Returns:
            当前状态，不存在返回 None
        """
        if self._react_graph is None:
            return None

        return self._react_graph.get_state(session_id)

    def get_mermaid_diagram(self) -> str:
        """获取 ReAct 工作流的 Mermaid 图表

        Returns:
            Mermaid 图表字符串
        """
        if self._react_graph is None:
            return "Error: LangGraph mode not enabled"

        return self._react_graph.get_mermaid_diagram()

    async def _log_operation(
        self,
        user_input: str,
        instruction: Instruction,
        risk: RiskLevel,
        confirmed: bool,
        exit_code: int,
        output: str,
    ) -> None:
        """记录操作到审计日志"""
        audit_worker = self._workers.get("audit")
        if audit_worker:
            await audit_worker.execute(
                "log_operation",
                {
                    "input": user_input,
                    "worker": instruction.worker,
                    "action": instruction.action,
                    "risk": risk,
                    "confirmed": "yes" if confirmed else "no",
                    "exit_code": exit_code,
                    "output": output,
                },
            )
