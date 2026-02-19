"""reason_node 策略模式 — 每种意图对应一个独立策略

将原 reason_node 中 200+ 行的 if-elif-else 拆分为独立策略类，
reason_node 变成一个简洁的路由器。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.context.environment import EnvironmentContext
from src.llm.client import LLMClient
from src.orchestrator.preprocessor import RequestPreprocessor
from src.orchestrator.prompt import PromptBuilder
from src.orchestrator.validation import validate_instruction
from src.types import ConversationEntry, Instruction, RiskLevel
from src.workers.base import BaseWorker


class ReasonResult:
    """策略执行结果"""

    __slots__ = (
        "instruction",
        "thinking",
        "is_final",
        "is_error",
        "error_message",
        "is_simple_intent",
    )

    def __init__(
        self,
        instruction: Optional[Instruction] = None,
        thinking: Optional[str] = None,
        is_final: Optional[bool] = None,
        is_error: bool = False,
        error_message: str = "",
        is_simple_intent: bool = False,
    ) -> None:
        self.instruction = instruction
        self.thinking = thinking
        self.is_final = is_final
        self.is_error = is_error
        self.error_message = error_message
        self.is_simple_intent = is_simple_intent

    @staticmethod
    def error(message: str) -> ReasonResult:
        return ReasonResult(is_error=True, error_message=message)


class ReasonContext:
    """策略共享的上下文，避免每个策略都持有全部依赖"""

    __slots__ = (
        "llm",
        "workers",
        "env_context",
        "prompt_builder",
        "preprocessor",
        "dry_run",
        "max_risk",
        "progress_callback",
    )

    def __init__(
        self,
        llm: LLMClient,
        workers: dict[str, BaseWorker],
        env_context: EnvironmentContext,
        prompt_builder: PromptBuilder,
        preprocessor: RequestPreprocessor,
        dry_run: bool,
        max_risk: RiskLevel,
        progress_callback: Optional[Callable[[str, str], None]],
    ) -> None:
        self.llm = llm
        self.workers = workers
        self.env_context = env_context
        self.prompt_builder = prompt_builder
        self.preprocessor = preprocessor
        self.dry_run = dry_run
        self.max_risk = max_risk
        self.progress_callback = progress_callback

    def report_progress(self, step: str, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(step, message)

    def available_workers_text(self) -> str:
        lines = []
        for name in sorted(self.workers.keys()):
            actions = self.workers[name].get_capabilities()
            lines.append(f"- {name}: {', '.join(actions)}")
        return "\n".join(lines)

    def build_fallback_instruction(
        self, user_input: str, error_message: str
    ) -> Optional[Instruction]:
        chat_worker = self.workers.get("chat")
        if not chat_worker or "respond" not in chat_worker.get_capabilities():
            return None
        message = (
            "指令校验失败，无法执行当前请求。\n"
            f"原因: {error_message}\n\n"
            "请更具体描述你的需求，或明确使用以下能力:\n"
            f"{self.available_workers_text()}\n\n"
            f"原始请求: {user_input}"
        )
        return Instruction(
            worker="chat",
            action="respond",
            args={"message": message},
            risk_level="safe",
        )


class ReasonStrategy(ABC):
    """推理策略基类"""

    @abstractmethod
    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        ...


class IdentityStrategy(ReasonStrategy):
    """自我介绍 / 身份询问 — 直接回复，不经过 LLM"""

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        chat_worker = ctx.workers.get("chat")
        if chat_worker and "respond" in chat_worker.get_capabilities():
            return ReasonResult(
                instruction=Instruction(
                    worker="chat",
                    action="respond",
                    args={
                        "message": (
                            "我是一个运维助手，可以帮你排查问题、部署项目、查看日志、"
                            "执行常用命令并解释输出。告诉我你的需求即可。"
                        )
                    },
                    risk_level="safe",
                ),
                is_final=True,
                is_simple_intent=True,
            )
        # 无 chat worker 时回退 LLM
        return await LLMDefaultStrategy().generate(
            ctx, user_input, preprocessed, history, thinking_history
        )


class ExplainShortcutStrategy(ReasonStrategy):
    """高置信度 explain — 直接生成 analyze 指令"""

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        ctx.report_progress("reasoning", "直接生成 analyze 指令（跳过 LLM）")
        return ReasonResult(
            instruction=Instruction(
                worker="analyze",
                action="explain",
                args={
                    "target": str(preprocessed.get("resolved_target")),
                    "type": str(preprocessed.get("target_type", "docker")),
                },
                risk_level="safe",
            ),
        )


class ExplainNeedsContextStrategy(ReasonStrategy):
    """explain 意图但需要先获取上下文（如 docker ps）"""

    LIST_COMMANDS: dict[str, str] = {
        "docker": "docker ps",
        "process": "ps aux",
        "port": "ss -tlnp",
        "file": "ls -la",
        "systemd": "systemctl list-units --type=service --state=running",
        "network": "ip addr",
    }

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        target_type = str(preprocessed.get("target_type", "docker"))
        cmd = self.LIST_COMMANDS.get(target_type, "docker ps")
        ctx.report_progress("reasoning", f"需要上下文，先执行: {cmd}")
        return ReasonResult(
            instruction=Instruction(
                worker="shell",
                action="execute_command",
                args={"command": cmd},
                risk_level="safe",
            ),
        )


class DeployStrategy(ReasonStrategy):
    """部署意图 — 优先用 deploy worker，否则走 LLM"""

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        repo_url = ctx.preprocessor.extract_repo_url(user_input)
        if not repo_url:
            return ReasonResult.error("无法提取 GitHub URL")

        target_dir = ctx.env_context.cwd

        # 有 deploy worker 时直接走
        if ctx.workers.get("deploy"):
            ctx.report_progress("reasoning", "生成一键部署指令")
            return ReasonResult(
                instruction=Instruction(
                    worker="deploy",
                    action="deploy",
                    args={"repo_url": repo_url, "target_dir": target_dir},
                    risk_level="medium",
                ),
            )

        # 没有 deploy worker 时用 LLM + 部署专用 prompt
        system_prompt = ctx.prompt_builder.build_deploy_prompt(
            ctx.env_context,
            repo_url=repo_url,
            target_dir=target_dir,
            available_workers=ctx.workers,
        )
        user_prompt = f"Deploy this project: {user_input}"

        instruction, error, thinking, is_final = await _generate_with_retry(
            ctx, system_prompt, user_prompt, user_input
        )
        if instruction is None:
            return ReasonResult.error(error)

        ctx.report_progress("reasoning", "生成部署指令")
        return ReasonResult(instruction=instruction, thinking=thinking, is_final=is_final)


class ForceSummarizeStrategy(ReasonStrategy):
    """迭代即将耗尽 — 强制生成最终总结"""

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        ctx.report_progress("reasoning", "迭代即将耗尽，生成最终总结...")

        system_prompt = ctx.prompt_builder.build_system_prompt(
            ctx.env_context, available_workers=ctx.workers, user_input=user_input
        )
        user_prompt = ctx.prompt_builder.build_user_prompt(
            user_input, history=history, thinking_history=thinking_history
        )
        user_prompt += (
            "\n\nCRITICAL: This is your LAST iteration. You MUST use chat.respond now "
            "to deliver a comprehensive summary of all findings to the user in Chinese. "
            "Do NOT execute any more commands. Summarize what you found and give recommendations."
        )

        instruction, error, thinking, _ = await _generate_with_retry(
            ctx, system_prompt, user_prompt, user_input
        )
        if instruction is None:
            return ReasonResult.error(error)

        # LLM 仍未生成 chat.respond 时，强制覆盖
        if instruction.worker != "chat" or instruction.action != "respond":
            findings = [
                f"- {e.instruction.worker}.{e.instruction.action}: {e.result.message}"
                for e in history
            ]
            findings_text = "\n".join(findings) if findings else "无"
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

        return ReasonResult(instruction=instruction, thinking=thinking, is_final=True)


class LLMDefaultStrategy(ReasonStrategy):
    """默认策略 — 调用 LLM 生成指令"""

    async def generate(
        self,
        ctx: ReasonContext,
        user_input: str,
        preprocessed: dict[str, object],
        history: list[ConversationEntry],
        thinking_history: list[str],
    ) -> ReasonResult:
        system_prompt = ctx.prompt_builder.build_system_prompt(
            ctx.env_context, available_workers=ctx.workers, user_input=user_input
        )
        user_prompt = ctx.prompt_builder.build_user_prompt(
            user_input, history=history, thinking_history=thinking_history
        )

        instruction, error, thinking, is_final = await _generate_with_retry(
            ctx, system_prompt, user_prompt, user_input
        )
        if instruction is None:
            return ReasonResult.error(error)

        intent = preprocessed.get("intent", "")
        is_simple = intent in ("greeting", "identity", "chat")
        if not is_simple:
            ctx.report_progress("reasoning", "指令生成完成")

        return ReasonResult(
            instruction=instruction,
            thinking=thinking,
            is_final=is_final,
            is_simple_intent=is_simple,
        )


# ---- 路由函数 ----

def select_strategy(
    preprocessed: dict[str, object],
    force_summarize: bool,
) -> ReasonStrategy:
    """根据预处理结果选择策略"""
    if force_summarize:
        return ForceSummarizeStrategy()

    intent = preprocessed.get("intent", "")

    if intent == "identity":
        return IdentityStrategy()

    if intent == "deploy":
        return DeployStrategy()

    if (
        preprocessed.get("confidence") == "high"
        and intent == "explain"
        and preprocessed.get("resolved_target")
    ):
        return ExplainShortcutStrategy()

    if (
        intent == "explain"
        and preprocessed.get("needs_context")
        and preprocessed.get("target_type")
    ):
        return ExplainNeedsContextStrategy()

    return LLMDefaultStrategy()


# ---- 共享工具函数 ----

async def _generate_with_retry(
    ctx: ReasonContext,
    system_prompt: str,
    user_prompt: str,
    user_input: str,
) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
    """生成指令并进行一次纠错重试

    自动选择 Function Calling 或文本 JSON 模式。
    """
    if ctx.llm.supports_function_calling:
        return await _generate_via_function_calling(ctx, system_prompt, user_prompt, user_input)
    return await _generate_via_text_json(ctx, system_prompt, user_prompt, user_input)


async def _generate_via_function_calling(
    ctx: ReasonContext,
    system_prompt: str,
    user_prompt: str,
    user_input: str,
) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
    """通过 Function Calling 生成指令"""
    result = await ctx.llm.generate_with_tools(system_prompt, user_prompt, ctx.workers)

    if result is not None:
        instruction = Instruction(
            worker=result.worker,
            action=result.action,
            args=result.args,
            risk_level="safe",
        )
        valid, error = validate_instruction(instruction, ctx.workers)
        if valid:
            return instruction, "", result.thinking, result.is_final

    return await _generate_via_text_json(ctx, system_prompt, user_prompt, user_input)


async def _generate_via_text_json(
    ctx: ReasonContext,
    system_prompt: str,
    user_prompt: str,
    user_input: str,
) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
    """通过文本 JSON 解析生成指令"""
    llm_response = await ctx.llm.generate(system_prompt, user_prompt)
    instruction, error, thinking, is_final = _parse_and_validate(ctx, llm_response)
    if instruction:
        return instruction, "", thinking, is_final

    # 一次纠错重试
    repair_prompt = _build_repair_prompt(ctx, user_input, error)
    llm_response = await ctx.llm.generate(system_prompt, repair_prompt)
    instruction, error, thinking, is_final = _parse_and_validate(ctx, llm_response)
    if instruction:
        return instruction, "", thinking, is_final

    fallback = ctx.build_fallback_instruction(user_input, error)
    if fallback:
        return fallback, "", None, True

    return None, error, None, None


def _parse_and_validate(
    ctx: ReasonContext, response: str
) -> tuple[Optional[Instruction], str, Optional[str], Optional[bool]]:
    """解析并校验 LLM 响应"""
    parsed = ctx.llm.parse_json_response(response)
    if parsed is None:
        return None, "Failed to parse LLM response JSON", None, None

    thinking = str(parsed["thinking"]) if "thinking" in parsed else None
    is_final = bool(parsed["is_final"]) if "is_final" in parsed else None

    action_dict = parsed.get("action")
    instruction_dict = (
        action_dict if isinstance(action_dict, dict) and "worker" in action_dict else parsed
    )

    args = instruction_dict.get("args", {})
    if not isinstance(args, dict):
        args = {}

    risk_level_raw = instruction_dict.get("risk_level", "safe")
    risk_level = str(risk_level_raw) if risk_level_raw in {"safe", "medium", "high"} else "safe"

    from pydantic import ValidationError

    try:
        instruction = Instruction(
            worker=str(instruction_dict.get("worker", "")),
            action=str(instruction_dict.get("action", "")),
            args=args,
            risk_level=risk_level,
        )
    except ValidationError as e:
        return None, f"Invalid instruction schema: {e}", thinking, is_final

    valid, error = validate_instruction(instruction, ctx.workers)
    if not valid:
        return None, error, thinking, is_final

    return instruction, "", thinking, is_final


def _build_repair_prompt(ctx: ReasonContext, user_input: str, error_message: str) -> str:
    """构建修复提示"""
    return (
        f"Your previous JSON was invalid: {error_message}\n\n"
        "Return ONLY a valid JSON object with fields:\n"
        '{"thinking": "your reasoning", "action": {"worker": "...", "action": "...", '
        '"args": {...}, "risk_level": "safe|medium|high"}, "is_final": false}\n\n'
        f"Allowed workers/actions:\n{ctx.available_workers_text()}\n\n"
        f"User request: {user_input}"
    )
