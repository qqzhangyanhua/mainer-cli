"""ReAct 循环节点实现"""

from __future__ import annotations

import re
from typing import Callable, Optional

from pydantic import ValidationError

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.graph.react_state import ReactState
from src.orchestrator.preprocessor import RequestPreprocessor
from src.orchestrator.prompt import PromptBuilder
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

    每个方法对应 LangGraph 状态图中的一个节点
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
        """初始化节点

        Args:
            llm_client: LLM 客户端
            workers: Worker 实例字典
            context: 环境上下文
            dry_run: 是否启用 dry-run 模式
            max_risk: 最大允许风险等级
            auto_approve_safe: safe 操作是否自动通过
            require_dry_run_for_high_risk: 高风险操作是否强制 dry-run
            progress_callback: 进度回调函数
        """
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

    @staticmethod
    def _risk_rank(risk: RiskLevel) -> int:
        ranks: dict[RiskLevel, int] = {
            "safe": 0,
            "medium": 1,
            "high": 2,
        }
        return ranks[risk]

    @staticmethod
    def _detect_permission_error(data: dict[str, object]) -> bool:
        """检查命令输出中是否包含权限错误关键词"""
        stderr = str(data.get("stderr", ""))
        stdout = str(data.get("stdout", ""))
        combined = f"{stderr} {stdout}"
        return any(pattern.search(combined) for pattern in PERMISSION_ERROR_PATTERNS)

    @staticmethod
    def _build_sudo_command(command: str) -> str:
        """在原命令前加 sudo，避免重复"""
        stripped = command.strip()
        if stripped.startswith("sudo "):
            return stripped
        return f"sudo {stripped}"

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

    def _parse_and_validate_instruction(
        self, response: str
    ) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
        """解析并校验 LLM 指令

        支持两种格式:
        1. 新格式: {"thinking": "...", "action": {...}, "is_final": bool}
        2. 旧格式: {"worker": "...", "action": "...", "args": {...}, "risk_level": "..."}

        Returns:
            (instruction, error, thinking, is_final)
        """
        parsed = self._llm.parse_json_response(response)
        if parsed is None:
            return None, "Failed to parse LLM response JSON", None, None

        # 提取 thinking 和 is_final（新格式）
        thinking = None
        is_final = None
        if "thinking" in parsed:
            thinking = str(parsed.get("thinking", ""))
        if "is_final" in parsed:
            is_final = bool(parsed.get("is_final", False))

        # 判断是新格式还是旧格式
        action_dict = parsed.get("action")
        if isinstance(action_dict, dict) and "worker" in action_dict:
            # 新格式：从 action 字段提取指令
            instruction_dict = action_dict
        else:
            # 旧格式：直接使用 parsed
            instruction_dict = parsed

        try:
            instruction = self._build_instruction(instruction_dict)
        except ValidationError as e:
            return None, f"Invalid instruction schema: {e}", thinking, is_final

        valid, error = validate_instruction(instruction, self._workers)
        if not valid:
            return None, error, thinking, is_final

        return instruction, "", thinking, is_final

    def _build_repair_prompt(self, user_input: str, error_message: str) -> str:
        """构建修复提示，要求 LLM 纠正无效指令"""
        return (
            "Your previous JSON was invalid: "
            f"{error_message}\n\n"
            "Return ONLY a valid JSON object with fields:\n"
            '{"thinking": "your reasoning", "action": {"worker": "...", "action": "...", '
            '"args": {...}, "risk_level": "safe|medium|high"}, "is_final": false}\n\n'
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
    ) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
        """生成指令并进行一次纠错重试

        注意: history 已通过 build_user_prompt 嵌入到 user_prompt 文本中，
        不再通过 generate() 的 history 参数传递，避免重复。

        Returns:
            (instruction, error, thinking, is_final)
        """
        llm_response = await self._llm.generate(system_prompt, user_prompt)
        instruction, error, thinking, is_final = self._parse_and_validate_instruction(llm_response)
        if instruction:
            return instruction, "", thinking, is_final

        repair_prompt = self._build_repair_prompt(user_input, error)
        llm_response = await self._llm.generate(system_prompt, repair_prompt)
        instruction, error, thinking, is_final = self._parse_and_validate_instruction(llm_response)
        if instruction:
            return instruction, "", thinking, is_final

        fallback = self._build_fallback_instruction(user_input, error)
        if fallback:
            return fallback, "", None, True

        return None, error, None, None

    def _build_conversation_history(
        self, state: ReactState
    ) -> tuple[list[ConversationEntry], list[str]]:
        """从消息历史构建 ConversationEntry 列表和 thinking 历史

        Args:
            state: 当前状态

        Returns:
            (ConversationEntry 列表, thinking 历史列表)
        """
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
                    # 提取 thinking 历史
                    thinking_val = _message_get(msg1, "thinking")
                    thinking_list.append(str(thinking_val) if thinking_val else "")
            i += 2

        return history, thinking_list

    async def preprocess_node(self, state: ReactState) -> dict[str, object]:
        """预处理节点：意图检测 + 指代解析"""
        user_input = state.get("user_input", "")
        history, _thinking_list = self._build_conversation_history(state)

        preprocessed = self._preprocessor.preprocess(user_input, history)

        # 简单意图不输出进度（greeting, identity, chat）
        if preprocessed.intent not in ("greeting", "identity", "chat"):
            self._report_progress("preprocessing", "分析请求...")

        return {
            "preprocessed": preprocessed.dict(),
        }

    async def reason_node(self, state: ReactState) -> dict[str, object]:
        """推理节点：LLM 生成下一步指令

        支持两种路径：
        1. 快捷路径：preprocessor 高置信度直接生成指令（不经过 LLM）
        2. LLM 路径：调用 LLM 生成 thinking + action + is_final
        """
        preprocessed_dict = state.get("preprocessed", {})
        intent = preprocessed_dict.get("intent", "")

        # 简单意图不输出进度
        is_simple_intent = intent in ("greeting", "identity", "chat")

        user_input = state.get("user_input", "")
        preprocessed_dict = state.get("preprocessed", {})
        history, thinking_history = self._build_conversation_history(state)

        # 默认值
        thinking: Optional[str] = None
        is_final: Optional[bool] = None

        # --- 强制总结路径（迭代即将耗尽）---
        if state.get("force_summarize", False):
            self._report_progress("reasoning", "迭代即将耗尽，生成最终总结...")
            system_prompt = self._prompt_builder.build_system_prompt(
                self._context,
                available_workers=self._workers,
            )
            # 在 user_prompt 中强制要求总结
            force_prompt = self._prompt_builder.build_user_prompt(
                user_input, history=history, thinking_history=thinking_history
            )
            force_prompt += (
                "\n\nCRITICAL: This is your LAST iteration. You MUST use chat.respond now "
                "to deliver a comprehensive summary of all findings to the user in Chinese. "
                "Do NOT execute any more commands. Summarize what you found and give recommendations."
            )
            instruction, error, thinking, is_final = await self._generate_instruction_with_retry(
                system_prompt=system_prompt,
                user_prompt=force_prompt,
                user_input=user_input,
                history=history,
            )
            if instruction is None:
                return {
                    "is_error": True,
                    "error_message": error,
                }
            # 如果 LLM 仍然没有生成 chat.respond，强制覆盖
            if instruction.worker != "chat" or instruction.action != "respond":
                # 构建基于历史的兜底总结
                findings_parts = []
                for entry in history:
                    findings_parts.append(
                        f"- {entry.instruction.worker}.{entry.instruction.action}: "
                        f"{entry.result.message}"
                    )
                findings_text = "\n".join(findings_parts) if findings_parts else "无"
                fallback_msg = (
                    f"以下是针对「{user_input}」的诊断结果（已达最大迭代次数）：\n\n"
                    f"{findings_text}\n\n"
                    f"建议根据以上信息进一步排查。"
                )
                instruction = Instruction(
                    worker="chat",
                    action="respond",
                    args={"message": thinking or fallback_msg},
                    risk_level="safe",
                )
            is_final = True
            return {
                "current_instruction": instruction.dict(),
                "is_simple_intent": False,
                "current_thinking": thinking,
                "llm_is_final": True,
                "force_summarize": False,  # 重置标志
            }

        # --- 快捷路径（不经过 LLM）---

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
                is_final = True
            else:
                system_prompt = self._prompt_builder.build_system_prompt(
                    self._context,
                    available_workers=self._workers,
                )
                user_prompt = self._prompt_builder.build_user_prompt(user_input, history=None)

                instruction, error, thinking, is_final = await self._generate_instruction_with_retry(
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
        # 高置信度 explain → 直接生成 analyze 指令
        elif (
            preprocessed_dict.get("confidence") == "high"
            and preprocessed_dict.get("intent") == "explain"
            and preprocessed_dict.get("resolved_target")
        ):
            instruction = Instruction(
                worker="analyze",
                action="explain",
                args={
                    "target": str(preprocessed_dict.get("resolved_target")),
                    "type": str(preprocessed_dict.get("target_type", "docker")),
                },
                risk_level="safe",
            )
            self._report_progress("reasoning", "直接生成 analyze 指令（跳过 LLM）")
        # explain 但需要先获取上下文
        elif (
            preprocessed_dict.get("intent") == "explain"
            and preprocessed_dict.get("needs_context")
            and preprocessed_dict.get("target_type")
        ):
            list_command = self._get_list_command(str(preprocessed_dict.get("target_type")))
            instruction = Instruction(
                worker="shell",
                action="execute_command",
                args={"command": list_command},
                risk_level="safe",
            )
            self._report_progress("reasoning", f"需要上下文，先执行: {list_command}")
        # 部署意图
        elif preprocessed_dict.get("intent") == "deploy":
            repo_url = self._preprocessor.extract_repo_url(user_input)
            target_dir = self._context.cwd
            if repo_url and self._workers.get("deploy"):
                instruction = Instruction(
                    worker="deploy",
                    action="deploy",
                    args={"repo_url": repo_url, "target_dir": target_dir},
                    risk_level="medium",
                )
                self._report_progress("reasoning", "生成一键部署指令")
            elif repo_url:
                system_prompt = self._prompt_builder.build_deploy_prompt(
                    self._context,
                    repo_url=repo_url,
                    target_dir=target_dir,
                    available_workers=self._workers,
                )
                user_prompt = f"Deploy this project: {user_input}"

                instruction, error, thinking, is_final = await self._generate_instruction_with_retry(
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
                self._report_progress("reasoning", "生成部署指令")
            else:
                return {
                    "is_error": True,
                    "error_message": "无法提取 GitHub URL",
                }

        # --- LLM 路径 ---
        else:
            system_prompt = self._prompt_builder.build_system_prompt(
                self._context,
                available_workers=self._workers,
            )
            user_prompt = self._prompt_builder.build_user_prompt(
                user_input, history=history, thinking_history=thinking_history
            )

            instruction, error, thinking, is_final = await self._generate_instruction_with_retry(
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
            if not is_simple_intent:
                self._report_progress("reasoning", "指令生成完成")

        # 指令校验（防止未知 Worker/Action）
        valid, error = validate_instruction(instruction, self._workers)
        if not valid:
            fallback = self._build_fallback_instruction(user_input, error)
            if fallback:
                instruction = fallback
                is_final = True
            else:
                return {
                    "is_error": True,
                    "error_message": error,
                }

        # 展示 thinking 内容
        if thinking and not is_simple_intent:
            self._report_progress("thinking", thinking)

        # 只对复杂操作显示指令详情
        if not is_simple_intent and instruction.worker != "chat":
            self._report_progress(
                "instruction",
                f"{instruction.worker}.{instruction.action}",
            )

        return {
            "current_instruction": instruction.dict(),
            "is_simple_intent": is_simple_intent,
            "current_thinking": thinking,
            "llm_is_final": is_final,
        }

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

        # 只对非 safe 操作显示安全检查
        if risk != "safe" and not is_simple_intent:
            risk_label = {"medium": "[!]", "high": "[!!]"}.get(risk, "[?]")
            self._report_progress("safety", f"{risk_label} 风险等级: {risk}")

        if self._risk_rank(risk) > self._risk_rank(self._max_risk):
            return {
                "is_error": True,
                "error_message": (
                    f"risk level {risk} exceeds configured max risk {self._max_risk}"
                ),
            }

        # 判断是否需要审批
        # 只有 high 风险操作需要用户确认（如 kill、rm、docker rm 等）
        # safe 和 medium（查看、安装等）直接执行，不打断用户
        needs_approval = risk == "high"

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
        is_simple_intent = state.get("is_simple_intent", False)

        # 只对复杂操作显示执行中
        if not is_simple_intent:
            self._report_progress("executing", "执行中...")

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

        # 添加到消息历史（包含 thinking）
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

        return {
            "worker_result": result.dict(),
            "messages": messages,
        }

    async def check_node(self, state: ReactState) -> dict[str, object]:
        """检查节点：判断任务是否完成

        完成判断优先级：
        1. LLM 的 is_final 标志（新逻辑）
        2. Worker 的 task_completed 标志（兼容旧逻辑）

        命令执行失败（exit code != 0）属于可恢复错误，
        回到 reason_node 让 LLM 分析错误并尝试替代方案。
        """
        result_dict = state.get("worker_result", {})
        worker_task_completed = bool(result_dict.get("task_completed", False))
        llm_is_final = state.get("llm_is_final")
        success = bool(result_dict.get("success", False))
        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", 5)

        if not success:
            # 判断是否为可恢复错误（命令执行失败，而非系统级错误）
            data = result_dict.get("data")
            is_command_failure = (
                isinstance(data, dict) and "exit_code" in data
            )

            # 权限错误检测：跳过恢复循环，直接建议 sudo 命令
            if is_command_failure and isinstance(data, dict) and self._detect_permission_error(data):
                original_cmd = str(data.get("command", ""))
                if original_cmd:
                    sudo_cmd = self._build_sudo_command(original_cmd)
                    message = str(result_dict.get("message", ""))
                    final_msg = (
                        f"权限不足，无法自动执行。请手动运行以下命令：\n\n"
                        f"  {sudo_cmd}\n\n"
                        f"原始错误：{message}"
                    )
                    self._report_progress(
                        "recovery",
                        f"检测到权限错误，生成建议命令: {sudo_cmd}",
                    )
                    return {
                        "task_completed": True,
                        "is_error": False,
                        "suggested_commands": [sudo_cmd],
                        "final_message": final_msg,
                    }

            recovery_count = int(state.get("error_recovery_count", 0))
            max_recovery = 2  # 最多尝试 2 次错误恢复

            if is_command_failure and recovery_count < max_recovery and iteration < max_iterations:
                # 可恢复：回到 reason_node，让 LLM 看到失败原因并尝试替代方案
                self._report_progress(
                    "recovery",
                    f"命令执行失败，尝试替代方案 ({recovery_count + 1}/{max_recovery})...",
                )
                return {
                    "iteration": iteration,
                    "error_recovery_count": recovery_count + 1,
                    "task_completed": False,
                    "is_error": False,
                }

            # 不可恢复或恢复次数耗尽：终止
            return {
                "is_error": True,
                "error_message": str(result_dict.get("message", "Unknown error")),
            }

        # Worker 级别的完成标志是确定性的（如 chat.respond），永远尊重
        if worker_task_completed:
            return {
                "task_completed": True,
                "final_message": str(result_dict.get("message", "")),
            }

        # Worker 未标记完成时，LLM 的 is_final 可以加速结束
        if llm_is_final is True:
            return {
                "task_completed": True,
                "final_message": str(result_dict.get("message", "")),
            }

        if iteration >= max_iterations:
            # 迭代耗尽：基于已收集的信息构建兜底总结，而不是直接报错
            self._report_progress(
                "summarizing",
                "已达到最大迭代次数，正在基于已收集信息生成总结...",
            )
            return await self._force_summarize_from_history(state)

        # 倒数第二轮：标记下一轮必须总结
        if iteration >= max_iterations - 1:
            self._report_progress(
                "warning",
                "即将达到最大迭代次数，下一步将给出总结。",
            )
            return {
                "iteration": iteration,
                "task_completed": False,
                "force_summarize": True,
            }

        # Worker 未完成 + LLM 未标记结束 → 继续循环
        return {
            "iteration": iteration,
            "task_completed": False,
        }

    async def _force_summarize_from_history(
        self, state: ReactState
    ) -> dict[str, object]:
        """迭代耗尽时，调用 LLM 基于已收集信息生成最终总结

        不再直接报错，而是让 LLM 综合所有历史结果给出有价值的诊断。
        """
        history, thinking_history = self._build_conversation_history(state)
        user_input = state.get("user_input", "")

        # 构建历史摘要
        findings: list[str] = []
        for idx, entry in enumerate(history):
            action = f"{entry.instruction.worker}.{entry.instruction.action}"
            result_msg = entry.result.message
            findings.append(f"- {action}: {result_msg}")

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
            system_prompt = "你是一个运维诊断助手。请基于已收集的信息给出简洁、有价值的中文诊断总结。"
            summary = await self._llm.generate(system_prompt, summarize_prompt)
            # 清理可能的 JSON 包装
            summary = summary.strip()
            if summary.startswith("{") and summary.endswith("}"):
                parsed = self._llm.parse_json_response(summary)
                if parsed and isinstance(parsed.get("message"), str):
                    summary = parsed["message"]
                elif parsed and isinstance(parsed.get("args"), dict):
                    summary = str(parsed["args"].get("message", summary))
        except Exception:
            summary = (
                f"诊断未完成（已达最大迭代次数）。\n\n"
                f"已执行的检查:\n{findings_text}\n\n"
                f"建议手动继续排查。"
            )

        return {
            "task_completed": True,
            "is_error": False,
            "final_message": summary,
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
