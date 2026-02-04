"""ReAct 循环引擎"""

from __future__ import annotations

from typing import Callable, Optional

from src.config.manager import OpsAIConfig
from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.prompt import PromptBuilder
from src.orchestrator.safety import check_safety
from src.types import ConversationEntry, Instruction, RiskLevel, WorkerResult
from src.workers.audit import AuditWorker
from src.workers.base import BaseWorker
from src.workers.system import SystemWorker


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
        confirmation_callback: Optional[Callable[[Instruction, RiskLevel], bool]] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化引擎

        Args:
            config: 配置对象
            confirmation_callback: 确认回调函数，用于高危操作确认
            dry_run: 是否启用 dry-run 模式
            progress_callback: 进度回调函数，接收 (step_name, message) 用于实时显示进度
        """
        self._config = config
        self._llm_client = LLMClient(config.llm)
        self._prompt_builder = PromptBuilder()
        self._context = EnvironmentContext()
        self._confirmation_callback = confirmation_callback
        self._dry_run = dry_run or config.safety.dry_run_by_default
        self._progress_callback = progress_callback

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

    def get_worker(self, name: str) -> Optional[BaseWorker]:
        """获取 Worker

        Args:
            name: Worker 名称

        Returns:
            Worker 实例，不存在返回 None
        """
        return self._workers.get(name)

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
    ) -> str:
        """执行 ReAct 循环

        Args:
            user_input: 用户输入
            max_iterations: 最大迭代次数，防止死循环

        Returns:
            最终结果消息
        """
        conversation_history: list[ConversationEntry] = []

        for iteration in range(max_iterations):
            # 1. Reason: LLM 生成下一步指令
            if self._progress_callback:
                self._progress_callback("reasoning", "🤔 Analyzing your request...")

            system_prompt = self._prompt_builder.build_system_prompt(self._context)
            user_prompt = self._prompt_builder.build_user_prompt(
                user_input, history=conversation_history
            )

            llm_response = await self._llm_client.generate(system_prompt, user_prompt)
            parsed = self._llm_client.parse_json_response(llm_response)

            if parsed is None:
                return f"Error: Failed to parse LLM response: {llm_response}"

            # 构建指令
            instruction = Instruction(
                worker=str(parsed.get("worker", "")),
                action=str(parsed.get("action", "")),
                args=parsed.get("args", {}),  # type: ignore[arg-type]
                risk_level=parsed.get("risk_level", "safe"),  # type: ignore[arg-type]
            )

            # 显示生成的指令
            if self._progress_callback:
                self._progress_callback(
                    "instruction",
                    f"📋 Instruction: {instruction.worker}.{instruction.action}(args={instruction.args})"
                )

            # 2. Safety Check
            risk = check_safety(instruction)
            if self._progress_callback:
                risk_emoji = {"safe": "✅", "medium": "⚠️", "high": "🚨"}.get(risk, "❓")
                self._progress_callback("safety", f"{risk_emoji} Risk level: {risk}")
            if risk in ["medium", "high"]:
                if self._confirmation_callback:
                    confirmed = self._confirmation_callback(instruction, risk)
                    if not confirmed:
                        # 记录拒绝
                        await self._log_operation(
                            user_input, instruction, risk, confirmed=False, exit_code=-1, output="Rejected by user"
                        )
                        return "Operation cancelled by user"
                else:
                    # CLI 模式无确认回调，自动拒绝
                    return f"Error: {risk.upper()}-risk operation requires TUI mode for confirmation"

            # 3. Act: 执行 Worker
            if self._progress_callback:
                self._progress_callback("executing", f"⚙️  Executing {instruction.worker}.{instruction.action}...")

            result = await self.execute_instruction(instruction)

            if self._progress_callback:
                status_emoji = "✅" if result.success else "❌"
                self._progress_callback("result", f"{status_emoji} {result.message}")

            # 4. 记录到审计日志
            await self._log_operation(
                user_input, instruction, risk, confirmed=True,
                exit_code=0 if result.success else 1,
                output=result.message,
            )

            # 5. 记录历史
            conversation_history.append(
                ConversationEntry(instruction=instruction, result=result)
            )

            # 6. 判断是否完成
            if result.task_completed:
                return result.message

        return "Task incomplete: reached maximum iterations"

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
