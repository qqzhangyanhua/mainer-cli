"""ReAct 循环节点实现

reason_node 通过策略模式委托给 reason_strategies.py，
本文件只保留节点调度和不涉及推理的节点实现。
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.graph.react_state import ReactState
from src.orchestrator.preprocessor import RequestPreprocessor
from src.orchestrator.prompt import PromptBuilder
from src.orchestrator.reason_strategies import ReasonContext, select_strategy
from src.orchestrator.safety import check_safety
from src.orchestrator.validation import validate_instruction
from src.types import ConversationEntry, Instruction, RiskLevel, WorkerResult
from src.workers.base import BaseWorker

# 权限错误匹配模式（不区分大小写）
PERMISSION_ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"operation not permitted", re.IGNORECASE),
    re.compile(r"requires? root", re.IGNORECASE),
    re.compile(r"must be run as root", re.IGNORECASE),
    re.compile(r"access denied", re.IGNORECASE),
    re.compile(r"EACCES", re.IGNORECASE),
    re.compile(r"insufficient permissions?", re.IGNORECASE),
    re.compile(r"not permitted to", re.IGNORECASE),
    re.compile(r"run .*as administrator", re.IGNORECASE),
]


class ReactNodes:
    """ReAct 循环节点

    每个方法对应 LangGraph 状态图中的一个节点。
    推理逻辑委托给 reason_strategies 模块。
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
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._llm = llm_client
        self._workers = workers
        self._context = context
        self._dry_run = dry_run
        self._max_risk = max_risk
        self._auto_approve_safe = auto_approve_safe
        self._require_dry_run_for_high_risk = require_dry_run_for_high_risk
        self._progress_callback = progress_callback

        self._preprocessor = RequestPreprocessor()
        self._prompt_builder = PromptBuilder()

        # 构建策略共享上下文
        self._reason_ctx = ReasonContext(
            llm=llm_client,
            workers=workers,
            env_context=context,
            prompt_builder=self._prompt_builder,
            preprocessor=self._preprocessor,
            dry_run=dry_run,
            max_risk=max_risk,
            progress_callback=progress_callback,
        )

    @staticmethod
    def _risk_rank(risk: RiskLevel) -> int:
        ranks: dict[RiskLevel, int] = {"safe": 0, "medium": 1, "high": 2}
        return ranks[risk]

    @staticmethod
    def _detect_permission_error(data: dict[str, object]) -> bool:
        stderr = str(data.get("stderr", ""))
        stdout = str(data.get("stdout", ""))
        combined = f"{stderr} {stdout}"
        return any(pattern.search(combined) for pattern in PERMISSION_ERROR_PATTERNS)

    @staticmethod
    def _build_sudo_command(command: str) -> str:
        stripped = command.strip()
        if stripped.startswith("sudo "):
            return stripped
        return f"sudo {stripped}"

    def _report_progress(self, step: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(step, message)

    def _build_conversation_history(
        self, state: ReactState
    ) -> tuple[list[ConversationEntry], list[str]]:
        """从消息历史构建 ConversationEntry 列表和 thinking 历史"""
        history: list[ConversationEntry] = []
        thinking_list: list[str] = []
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

        i = 0
        while i < len(messages) - 1:
            msg1 = messages[i]
            msg2 = messages[i + 1]

            if _message_role(msg1) == "assistant" and _message_role(msg2) == "system":
                inst_dict = _message_get(msg1, "instruction")
                res_dict = _message_get(msg2, "result")

                if isinstance(inst_dict, dict) and isinstance(res_dict, dict):
                    instruction = Instruction(
                        worker=str(inst_dict.get("worker", "")),
                        action=str(inst_dict.get("action", "")),
                        args=inst_dict.get("args", {}),
                        risk_level=inst_dict.get("risk_level", "safe"),
                        dry_run=bool(inst_dict.get("dry_run", False)),
                    )
                    result = WorkerResult(
                        success=bool(res_dict.get("success", False)),
                        data=res_dict.get("data"),
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
                    thinking_val = _message_get(msg1, "thinking")
                    thinking_list.append(str(thinking_val) if thinking_val else "")
            i += 2

        return history, thinking_list

    # ---- 节点实现 ----

    async def preprocess_node(self, state: ReactState) -> dict[str, object]:
        """预处理节点：意图检测 + 指代解析"""
        user_input = state.get("user_input", "")
        history, _ = self._build_conversation_history(state)

        preprocessed = self._preprocessor.preprocess(user_input, history)

        if preprocessed.intent not in ("greeting", "identity", "chat"):
            self._report_progress("preprocessing", "分析请求...")

        return {"preprocessed": preprocessed.dict()}

    async def reason_node(self, state: ReactState) -> dict[str, object]:
        """推理节点：通过策略模式路由到具体实现"""
        user_input = state.get("user_input", "")
        preprocessed_dict = state.get("preprocessed") or {}
        force_summarize = bool(state.get("force_summarize", False))
        history, thinking_history = self._build_conversation_history(state)

        # 选择策略并执行
        strategy = select_strategy(preprocessed_dict, force_summarize)
        result = await strategy.generate(
            self._reason_ctx, user_input, preprocessed_dict, history, thinking_history
        )

        if result.is_error:
            return {"is_error": True, "error_message": result.error_message}

        instruction = result.instruction
        if instruction is None:
            return {"is_error": True, "error_message": "Strategy returned no instruction"}

        # 统一校验（防止策略生成无效指令）
        valid, error = validate_instruction(instruction, self._workers)
        if not valid:
            fallback = self._reason_ctx.build_fallback_instruction(user_input, error)
            if fallback:
                instruction = fallback
                result.is_final = True
            else:
                return {"is_error": True, "error_message": error}

        # 展示 thinking 和指令详情
        if result.thinking and not result.is_simple_intent:
            self._report_progress("thinking", result.thinking)
        if not result.is_simple_intent and instruction.worker != "chat":
            self._report_progress("instruction", f"{instruction.worker}.{instruction.action}")

        state_update: dict[str, object] = {
            "current_instruction": instruction.dict(),
            "is_simple_intent": result.is_simple_intent,
            "current_thinking": result.thinking,
            "llm_is_final": result.is_final,
        }
        if force_summarize:
            state_update["force_summarize"] = False
        return state_update

    async def safety_node(self, state: ReactState) -> dict[str, object]:
        """安全检查节点"""
        is_simple_intent = state.get("is_simple_intent", False)

        inst_dict = state.get("current_instruction", {})
        instruction = Instruction(
            worker=str(inst_dict.get("worker", "")),
            action=str(inst_dict.get("action", "")),
            args=inst_dict.get("args", {}),  # type: ignore[arg-type]
            risk_level=inst_dict.get("risk_level", "safe"),  # type: ignore[arg-type]
            dry_run=bool(inst_dict.get("dry_run", False)),
        )

        risk = check_safety(instruction)

        if risk != "safe" and not is_simple_intent:
            risk_label = {"medium": "[!]", "high": "[!!]"}.get(risk, "[?]")
            self._report_progress("safety", f"{risk_label} 风险等级: {risk}")

        if self._risk_rank(risk) > self._risk_rank(self._max_risk):
            return {
                "is_error": True,
                "error_message": f"risk level {risk} exceeds configured max risk {self._max_risk}",
            }

        needs_approval = risk == "high"
        return {
            "risk_level": risk,
            "needs_approval": needs_approval,
            "approval_granted": False,
        }

    async def approve_node(self, state: ReactState) -> dict[str, object]:
        """审批节点：等待用户确认"""
        self._report_progress("approve", "等待用户确认...")
        return {"needs_approval": True}

    async def execute_node(self, state: ReactState) -> dict[str, object]:
        """执行节点：调用 Worker"""
        is_simple_intent = state.get("is_simple_intent", False)
        if not is_simple_intent:
            self._report_progress("executing", "执行中...")

        inst_dict = state.get("current_instruction", {})
        instruction = Instruction(
            worker=str(inst_dict.get("worker", "")),
            action=str(inst_dict.get("action", "")),
            args=inst_dict.get("args", {}),  # type: ignore[arg-type]
            risk_level=inst_dict.get("risk_level", "safe"),  # type: ignore[arg-type]
        )

        worker = self._workers.get(instruction.worker)
        if worker is None:
            return {"is_error": True, "error_message": f"Unknown worker: {instruction.worker}"}

        args = instruction.args.copy()
        if self._dry_run or instruction.dry_run:
            args["dry_run"] = True

        result = await worker.execute(instruction.action, args)

        status_emoji = "OK" if result.success else "FAIL"
        self._report_progress("result", f"{status_emoji} {result.message}")

        await self._log_operation(state, instruction, result)

        current_thinking = state.get("current_thinking")
        messages = list(state.get("messages", []))
        messages.append(
            {
                "role": "assistant",
                "content": f"Execute: {instruction.worker}.{instruction.action}",
                "instruction": instruction.dict(),
                "user_input": state.get("user_input"),
                "thinking": current_thinking or "",
            }
        )
        messages.append(
            {
                "role": "system",
                "content": result.message,
                "result": result.dict(),
            }
        )

        return {"worker_result": result.dict(), "messages": messages}

    async def check_node(self, state: ReactState) -> dict[str, object]:
        """检查节点：判断任务是否完成"""
        result_dict = state.get("worker_result", {})
        worker_task_completed = bool(result_dict.get("task_completed", False))
        llm_is_final = state.get("llm_is_final")
        success = bool(result_dict.get("success", False))
        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", 5)

        if not success:
            return self._handle_failure(state, result_dict, iteration, max_iterations)

        if worker_task_completed:
            return {"task_completed": True, "final_message": str(result_dict.get("message", ""))}

        if llm_is_final is True:
            return {"task_completed": True, "final_message": str(result_dict.get("message", ""))}

        if iteration >= max_iterations:
            self._report_progress("summarizing", "已达到最大迭代次数，正在生成总结...")
            return await self._force_summarize_from_history(state)

        if iteration >= max_iterations - 1:
            self._report_progress("warning", "即将达到最大迭代次数，下一步将给出总结。")
            return {"iteration": iteration, "task_completed": False, "force_summarize": True}

        return {"iteration": iteration, "task_completed": False}

    def _handle_failure(
        self,
        state: ReactState,
        result_dict: dict[str, object],
        iteration: int,
        max_iterations: int,
    ) -> dict[str, object]:
        """处理执行失败：权限错误检测 + 可恢复错误重试"""
        data = result_dict.get("data")
        is_command_failure = isinstance(data, dict) and "exit_code" in data

        # 权限错误 → 直接建议 sudo
        if is_command_failure and isinstance(data, dict) and self._detect_permission_error(data):
            original_cmd = str(data.get("command", ""))
            if original_cmd:
                sudo_cmd = self._build_sudo_command(original_cmd)
                message = str(result_dict.get("message", ""))
                self._report_progress("recovery", f"检测到权限错误，建议: {sudo_cmd}")
                return {
                    "task_completed": True,
                    "is_error": False,
                    "suggested_commands": [sudo_cmd],
                    "final_message": (
                        f"权限不足，无法自动执行。请手动运行以下命令：\n\n"
                        f"  {sudo_cmd}\n\n"
                        f"原始错误：{message}"
                    ),
                }

        recovery_count = int(state.get("error_recovery_count", 0))
        max_recovery = 2

        if is_command_failure and recovery_count < max_recovery and iteration < max_iterations:
            self._report_progress(
                "recovery", f"命令失败，尝试替代方案 ({recovery_count + 1}/{max_recovery})..."
            )
            return {
                "iteration": iteration,
                "error_recovery_count": recovery_count + 1,
                "task_completed": False,
                "is_error": False,
            }

        return {
            "is_error": True,
            "error_message": str(result_dict.get("message", "Unknown error")),
        }

    async def _force_summarize_from_history(self, state: ReactState) -> dict[str, object]:
        """迭代耗尽时，调用 LLM 生成最终总结"""
        history, _ = self._build_conversation_history(state)
        user_input = state.get("user_input", "")

        findings = [
            f"- {e.instruction.worker}.{e.instruction.action}: {e.result.message}"
            for e in history
        ]
        findings_text = "\n".join(findings) if findings else "（无历史记录）"

        summarize_prompt = (
            f"你已经执行了以下诊断步骤，但迭代次数已用完，必须立即给出最终总结。\n\n"
            f"用户请求: {user_input}\n\n"
            f"已执行的步骤和结果:\n{findings_text}\n\n"
            f"请基于以上已收集的信息，用中文给出综合诊断总结。"
            f"包括：已确认的事实、发现的问题、可能的原因、建议的下一步操作。\n"
            f"如果信息不足以得出完整结论，请说明还需要检查什么。\n\n"
            f"直接返回总结文本，不要返回 JSON。"
        )

        try:
            system_prompt = (
                "你是一个运维诊断助手。"
                "请基于已收集的信息给出简洁、有价值的中文诊断总结。"
            )
            summary = await self._llm.generate(system_prompt, summarize_prompt)
            summary = summary.strip()
            if summary.startswith("{") and summary.endswith("}"):
                parsed = self._llm.parse_json_response(summary)
                if parsed and isinstance(parsed.get("message"), str):
                    summary = str(parsed["message"])
                elif parsed:
                    args_val = parsed.get("args")
                    if isinstance(args_val, dict):
                        summary = str(args_val.get("message", summary))
        except Exception:
            summary = (
                f"诊断未完成（已达最大迭代次数）。\n\n"
                f"已执行的检查:\n{findings_text}\n\n"
                f"建议手动继续排查。"
            )

        return {"task_completed": True, "is_error": False, "final_message": summary}

    async def error_node(self, state: ReactState) -> dict[str, object]:
        """错误处理节点"""
        error_message = state.get("error_message", "Unknown error")
        self._report_progress("error", f"ERROR: {error_message}")
        return {
            "is_error": True,
            "task_completed": True,
            "final_message": f"Error: {error_message}",
        }

    async def _log_operation(
        self, state: ReactState, instruction: Instruction, result: WorkerResult
    ) -> None:
        """记录操作到审计日志"""
        if result.simulated or self._dry_run or instruction.dry_run:
            return
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
