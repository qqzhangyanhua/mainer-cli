"""ReAct 循环节点实现"""

from __future__ import annotations

from typing import Callable, Optional

from pydantic import ValidationError

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.graph.react_state import ReactState
from src.orchestrator.preprocessor import RequestPreprocessor
from src.orchestrator.prompt import PromptBuilder
from src.orchestrator.safety import check_safety
from src.orchestrator.validation import validate_instruction
from src.types import ConversationEntry, Instruction, WorkerResult
from src.workers.base import BaseWorker


class ReactNodes:
    """ReAct 循环节点

    每个方法对应 LangGraph 状态图中的一个节点
    """

    def __init__(
        self,
        llm_client: LLMClient,
        workers: dict[str, BaseWorker],
        context: EnvironmentContext,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化节点

        Args:
            llm_client: LLM 客户端
            workers: Worker 实例字典
            context: 环境上下文
            dry_run: 是否启用 dry-run 模式
            progress_callback: 进度回调函数
        """
        self._llm = llm_client
        self._workers = workers
        self._context = context
        self._dry_run = dry_run
        self._progress_callback = progress_callback

        self._preprocessor = RequestPreprocessor()
        self._prompt_builder = PromptBuilder()

    def _report_progress(self, step: str, message: str) -> None:
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(step, message)

    def _available_workers_text(self) -> str:
        """构建可用 Worker/Action 列表文本"""
        lines = []
        for worker_name in sorted(self._workers.keys()):
            actions = self._workers[worker_name].get_capabilities()
            lines.append(f"- {worker_name}: {', '.join(actions)}")
        return "\n".join(lines)

    def _build_instruction(self, parsed: dict[str, object]) -> Instruction:
        """从解析后的 JSON 构建指令，带基础容错"""
        args = parsed.get("args", {})
        if not isinstance(args, dict):
            args = {}

        risk_level = parsed.get("risk_level", "safe")
        if risk_level not in {"safe", "medium", "high"}:
            risk_level = "safe"

        return Instruction(
            worker=str(parsed.get("worker", "")),
            action=str(parsed.get("action", "")),
            args=args,  # type: ignore[arg-type]
            risk_level=risk_level,  # type: ignore[arg-type]
        )

    def _build_fallback_instruction(
        self, user_input: str, error_message: str
    ) -> Optional[Instruction]:
        """构建兜底指令：校验失败时回退到 chat.respond"""
        chat_worker = self._workers.get("chat")
        if not chat_worker or "respond" not in chat_worker.get_capabilities():
            return None

        message = (
            "指令校验失败，无法执行当前请求。\n"
            f"原因: {error_message}\n\n"
            "请更具体描述你的需求，或明确使用以下能力:\n"
            f"{self._available_workers_text()}\n\n"
            f"原始请求: {user_input}"
        )
        return Instruction(
            worker="chat",
            action="respond",
            args={"message": message},
            risk_level="safe",
        )

    def _parse_and_validate_instruction(self, response: str) -> tuple[Optional[Instruction], str]:
        """解析并校验 LLM 指令"""
        parsed = self._llm.parse_json_response(response)
        if parsed is None:
            return None, "Failed to parse LLM response JSON"

        try:
            instruction = self._build_instruction(parsed)
        except ValidationError as e:
            return None, f"Invalid instruction schema: {e}"

        valid, error = validate_instruction(instruction, self._workers)
        if not valid:
            return None, error

        return instruction, ""

    def _build_repair_prompt(self, user_input: str, error_message: str) -> str:
        """构建修复提示，要求 LLM 纠正无效指令"""
        return (
            "Your previous JSON was invalid: "
            f"{error_message}\n\n"
            "Return ONLY a valid JSON object with fields:\n"
            '{"worker": "...", "action": "...", "args": {...}, "risk_level": "safe|medium|high"}\n\n'
            "Allowed workers/actions:\n"
            f"{self._available_workers_text()}\n\n"
            f"User request: {user_input}"
        )

    async def _generate_instruction_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        user_input: str,
        history: list[ConversationEntry],
    ) -> tuple[Optional[Instruction], str]:
        """生成指令并进行一次纠错重试"""
        llm_response = await self._llm.generate(system_prompt, user_prompt, history=history)
        instruction, error = self._parse_and_validate_instruction(llm_response)
        if instruction:
            return instruction, ""

        repair_prompt = self._build_repair_prompt(user_input, error)
        llm_response = await self._llm.generate(system_prompt, repair_prompt, history=history)
        instruction, error = self._parse_and_validate_instruction(llm_response)
        if instruction:
            return instruction, ""

        fallback = self._build_fallback_instruction(user_input, error)
        if fallback:
            return fallback, ""

        return None, error

    def _build_conversation_history(self, state: ReactState) -> list[ConversationEntry]:
        """从消息历史构建 ConversationEntry 列表

        Args:
            state: 当前状态

        Returns:
            ConversationEntry 列表
        """
        history: list[ConversationEntry] = []
        messages = state.get("messages", [])

        def _message_role(message: object) -> Optional[str]:
            if isinstance(message, dict):
                role = message.get("role")
            else:
                role = getattr(message, "type", None)
            if role == "ai":
                return "assistant"
            if role == "human":
                return "user"
            return role

        def _message_get(message: object, key: str) -> object:
            if isinstance(message, dict):
                return message.get(key)
            additional = getattr(message, "additional_kwargs", None)
            if isinstance(additional, dict):
                return additional.get(key)
            return None

        # 每两条消息为一组（assistant 的指令 + 系统返回的结果）
        i = 0
        while i < len(messages) - 1:
            msg1 = messages[i]
            msg2 = messages[i + 1]

            if _message_role(msg1) == "assistant" and _message_role(msg2) == "system":
                # 解析 assistant 消息中的 instruction
                inst_dict = _message_get(msg1, "instruction")
                res_dict = _message_get(msg2, "result")

                if isinstance(inst_dict, dict) and isinstance(res_dict, dict):
                    instruction = Instruction(
                        worker=str(inst_dict.get("worker", "")),
                        action=str(inst_dict.get("action", "")),
                        args=inst_dict.get("args", {}),  # type: ignore[arg-type]
                        risk_level=inst_dict.get("risk_level", "safe"),  # type: ignore[arg-type]
                        dry_run=bool(inst_dict.get("dry_run", False)),
                    )

                    result = WorkerResult(
                        success=bool(res_dict.get("success", False)),
                        data=res_dict.get("data"),  # type: ignore[arg-type]
                        message=str(res_dict.get("message", "")),
                        task_completed=bool(res_dict.get("task_completed", False)),
                        simulated=bool(res_dict.get("simulated", False)),
                    )

                    history.append(
                        ConversationEntry(
                            instruction=instruction,
                            result=result,
                            user_input=_message_get(msg1, "user_input"),  # type: ignore[arg-type]
                        )
                    )
            i += 2

        return history

    async def preprocess_node(self, state: ReactState) -> dict[str, object]:
        """预处理节点：意图检测 + 指代解析"""
        self._report_progress("preprocessing", "🔍 分析请求意图...")

        user_input = state.get("user_input", "")
        history = self._build_conversation_history(state)

        preprocessed = self._preprocessor.preprocess(user_input, history)

        self._report_progress(
            "preprocessing",
            f"✅ Intent: {preprocessed.intent} (confidence: {preprocessed.confidence})",
        )

        return {
            "preprocessed": preprocessed.dict(),
        }

    async def reason_node(self, state: ReactState) -> dict[str, object]:
        """推理节点：LLM 生成下一步指令"""
        self._report_progress("reasoning", "🤔 生成执行计划...")

        user_input = state.get("user_input", "")
        preprocessed_dict = state.get("preprocessed", {})
        history = self._build_conversation_history(state)

        # 自我介绍/身份询问 - 直接回复
        if preprocessed_dict.get("intent") == "identity":
            chat_worker = self._workers.get("chat")
            if chat_worker and "respond" in chat_worker.get_capabilities():
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
                self._report_progress("reasoning", "✅ 生成身份介绍回复")
            else:
                system_prompt = self._prompt_builder.build_system_prompt(
                    self._context,
                    available_workers=self._workers,
                )
                user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

                instruction, error = await self._generate_instruction_with_retry(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_input=user_input,
                    history=history,
                )
                if instruction is None:
                    return {
                        "is_error": True,
                        "error_message": error,
                    }
        # 检查是否可以跳过 LLM（高置信度的 explain 意图）
        elif (
            preprocessed_dict.get("confidence") == "high"
            and preprocessed_dict.get("intent") == "explain"
            and preprocessed_dict.get("resolved_target")
        ):
            # 直接生成 Instruction
            instruction = Instruction(
                worker="analyze",
                action="explain",
                args={
                    "target": str(preprocessed_dict.get("resolved_target")),
                    "type": str(preprocessed_dict.get("target_type", "docker")),
                },
                risk_level="safe",
            )

            self._report_progress("reasoning", "✅ 直接生成 analyze 指令（跳过 LLM）")
        elif (
            preprocessed_dict.get("intent") == "explain"
            and preprocessed_dict.get("needs_context")
            and preprocessed_dict.get("target_type")
        ):
            # 需要先获取上下文
            list_command = self._get_list_command(str(preprocessed_dict.get("target_type")))
            instruction = Instruction(
                worker="shell",
                action="execute_command",
                args={"command": list_command},
                risk_level="safe",
            )

            self._report_progress("reasoning", f"✅ 需要上下文，先执行: {list_command}")
        elif preprocessed_dict.get("intent") == "deploy":
            # 部署意图 - 直接使用一键部署
            repo_url = self._preprocessor.extract_repo_url(user_input)
            if repo_url and self._workers.get("deploy"):
                instruction = Instruction(
                    worker="deploy",
                    action="deploy",
                    args={"repo_url": repo_url, "target_dir": "~/projects"},
                    risk_level="medium",
                )
                self._report_progress("reasoning", "✅ 生成一键部署指令")
            elif repo_url:
                # 缺少 deploy worker，回退到 LLM 部署 prompt
                system_prompt = self._prompt_builder.build_deploy_prompt(
                    self._context,
                    repo_url=repo_url,
                    target_dir="~/projects",
                    available_workers=self._workers,
                )
                user_prompt = f"Deploy this project: {user_input}"

                instruction, error = await self._generate_instruction_with_retry(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_input=user_input,
                    history=history,
                )
                if instruction is None:
                    return {
                        "is_error": True,
                        "error_message": error,
                    }
                self._report_progress("reasoning", "✅ 生成部署指令")
            else:
                return {
                    "is_error": True,
                    "error_message": "无法提取 GitHub URL",
                }
        else:
            # 普通流程：调用 LLM
            system_prompt = self._prompt_builder.build_system_prompt(
                self._context,
                available_workers=self._workers,
            )
            user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

            instruction, error = await self._generate_instruction_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                user_input=user_input,
                history=history,
            )
            if instruction is None:
                return {
                    "is_error": True,
                    "error_message": error,
                }
            self._report_progress("reasoning", "✅ LLM 生成指令完成")

        # 指令校验（防止未知 Worker/Action）
        valid, error = validate_instruction(instruction, self._workers)
        if not valid:
            fallback = self._build_fallback_instruction(user_input, error)
            if fallback:
                instruction = fallback
            else:
                return {
                    "is_error": True,
                    "error_message": error,
                }

        # 显示生成的指令
        self._report_progress(
            "instruction",
            f"📋 {instruction.worker}.{instruction.action}({instruction.args})",
        )

        return {
            "current_instruction": instruction.dict(),
        }

    async def safety_node(self, state: ReactState) -> dict[str, object]:
        """安全检查节点"""
        self._report_progress("safety", "🔒 安全检查...")

        inst_dict = state.get("current_instruction", {})
        instruction = Instruction(
            worker=str(inst_dict.get("worker", "")),
            action=str(inst_dict.get("action", "")),
            args=inst_dict.get("args", {}),  # type: ignore[arg-type]
            risk_level=inst_dict.get("risk_level", "safe"),  # type: ignore[arg-type]
        )

        risk = check_safety(instruction)

        risk_emoji = {"safe": "✅", "medium": "⚠️", "high": "🚨"}.get(risk, "❓")
        self._report_progress("safety", f"{risk_emoji} Risk level: {risk}")

        # 判断是否需要审批
        needs_approval = risk in ["medium", "high"]

        return {
            "risk_level": risk,
            "needs_approval": needs_approval,
            "approval_granted": False,  # 重置确认状态
        }

    async def approve_node(self, state: ReactState) -> dict[str, object]:
        """审批节点：等待用户确认（会触发 interrupt）"""
        self._report_progress("approve", "⏸️  等待用户确认...")

        # LangGraph 会在此处暂停（如果配置了 interrupt_before=["approve"]）
        # 外部需要调用 graph.update_state() 来设置 approval_granted=True

        return {
            "needs_approval": True,
        }

    async def execute_node(self, state: ReactState) -> dict[str, object]:
        """执行节点：调用 Worker"""
        self._report_progress("executing", "⚙️  执行中...")

        inst_dict = state.get("current_instruction", {})
        instruction = Instruction(
            worker=str(inst_dict.get("worker", "")),
            action=str(inst_dict.get("action", "")),
            args=inst_dict.get("args", {}),  # type: ignore[arg-type]
            risk_level=inst_dict.get("risk_level", "safe"),  # type: ignore[arg-type]
        )

        # 获取 Worker
        worker = self._workers.get(instruction.worker)
        if worker is None:
            return {
                "is_error": True,
                "error_message": f"Unknown worker: {instruction.worker}",
            }

        # 注入 dry_run 参数
        args = instruction.args.copy()
        if self._dry_run or instruction.dry_run:
            args["dry_run"] = True

        # 执行
        result = await worker.execute(instruction.action, args)

        status_emoji = "✅" if result.success else "❌"
        self._report_progress("result", f"{status_emoji} {result.message}")

        # 记录审计日志
        await self._log_operation(state, instruction, result)

        # 添加到消息历史
        messages = list(state.get("messages", []))
        messages.append(
            {
                "role": "assistant",
                "content": f"Execute: {instruction.worker}.{instruction.action}",
                "instruction": instruction.dict(),
                "user_input": state.get("user_input"),
            }
        )
        messages.append(
            {
                "role": "system",
                "content": result.message,
                "result": result.dict(),
            }
        )

        return {
            "worker_result": result.dict(),
            "messages": messages,
        }

    async def check_node(self, state: ReactState) -> dict[str, object]:
        """检查节点：判断任务是否完成"""
        result_dict = state.get("worker_result", {})
        task_completed = bool(result_dict.get("task_completed", False))
        success = bool(result_dict.get("success", False))

        if not success:
            return {
                "is_error": True,
                "error_message": str(result_dict.get("message", "Unknown error")),
            }

        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", 5)

        if task_completed:
            return {
                "task_completed": True,
                "final_message": str(result_dict.get("message", "")),
            }

        if iteration >= max_iterations:
            return {
                "is_error": True,
                "error_message": f"Reached maximum iterations ({max_iterations})",
            }

        return {
            "iteration": iteration,
            "task_completed": False,
        }

    async def error_node(self, state: ReactState) -> dict[str, object]:
        """错误处理节点"""
        error_message = state.get("error_message", "Unknown error")
        self._report_progress("error", f"❌ {error_message}")

        return {
            "is_error": True,
            "task_completed": True,
            "final_message": f"Error: {error_message}",
        }

    async def _log_operation(
        self,
        state: ReactState,
        instruction: Instruction,
        result: WorkerResult,
    ) -> None:
        """记录操作到审计日志"""
        audit_worker = self._workers.get("audit")
        if audit_worker:
            await audit_worker.execute(
                "log_operation",
                {
                    "input": state.get("user_input", ""),
                    "worker": instruction.worker,
                    "action": instruction.action,
                    "risk": state.get("risk_level", "safe"),
                    "confirmed": "yes" if state.get("approval_granted") else "auto",
                    "exit_code": 0 if result.success else 1,
                    "output": result.message,
                },
            )

    def _get_list_command(self, target_type: str) -> str:
        """根据目标类型返回列表命令"""
        commands = {
            "docker": "docker ps",
            "process": "ps aux",
            "port": "ss -tlnp",
            "file": "ls -la",
            "systemd": "systemctl list-units --type=service --state=running",
            "network": "ip addr",
        }
        return commands.get(target_type, "docker ps")
