"""指令构建与校验 - 从 OrchestratorEngine 提取的指令生成逻辑"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from src.llm.client import LLMClient
from src.orchestrator.validation import validate_instruction
from src.types import ConversationEntry, Instruction, WorkerResult
from src.workers.base import BaseWorker


def build_instruction(parsed: dict[str, object]) -> Instruction:
    """从解析后的 JSON 构建指令，带基础容错"""
    args = parsed.get("args", {})
    if not isinstance(args, dict):
        args = {}

    risk_level = parsed.get("risk_level", "safe")
    if risk_level not in {"safe", "medium", "high"}:
        risk_level = "safe"

    dry_run = parsed.get("dry_run", False)
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() == "true"

    return Instruction(
        worker=str(parsed.get("worker", "")),
        action=str(parsed.get("action", "")),
        args=args,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        dry_run=bool(dry_run),
    )


def build_fallback_instruction(
    user_input: str,
    error_message: str,
    workers: dict[str, BaseWorker],
) -> Optional[Instruction]:
    """构建兜底指令：校验失败时回退到 chat.respond"""
    chat_worker = workers.get("chat")
    if not chat_worker or "respond" not in chat_worker.get_capabilities():
        return None

    message = (
        "指令校验失败，无法执行当前请求。\n"
        f"原因: {error_message}\n\n"
        "请更具体描述你的需求，或明确使用以下能力：\n"
        f"{available_workers_text(workers)}\n\n"
        f"原始请求: {user_input}"
    )
    return Instruction(
        worker="chat",
        action="respond",
        args={"message": message},
        risk_level="safe",
    )


def available_workers_text(workers: dict[str, BaseWorker]) -> str:
    """构建可用 Worker/Action 列表文本"""
    lines = []
    for worker_name in sorted(workers.keys()):
        actions = workers[worker_name].get_capabilities()
        lines.append(f"- {worker_name}: {', '.join(actions)}")
    return "\n".join(lines)


def parse_and_validate_instruction(
    response: str,
    llm_client: LLMClient,
    workers: dict[str, BaseWorker],
) -> tuple[Optional[Instruction], str]:
    """解析并校验 LLM 指令"""
    parsed = llm_client.parse_json_response(response)
    if parsed is None:
        return None, "Failed to parse LLM response JSON"

    try:
        instruction = build_instruction(parsed)
    except ValidationError as e:
        return None, f"Invalid instruction schema: {e}"

    valid, error = validate_instruction(instruction, workers)
    if not valid:
        return None, error

    return instruction, ""


def build_repair_prompt(
    user_input: str,
    error_message: str,
    workers: dict[str, BaseWorker],
) -> str:
    """构建修复提示，要求 LLM 纠正无效指令"""
    json_format = (
        '{"worker": "...", "action": "...", "args": {...}, "risk_level": "safe|medium|high"}'
    )
    return (
        "Your previous JSON was invalid: "
        f"{error_message}\n\n"
        "Return ONLY a valid JSON object with fields:\n"
        f"{json_format}\n\n"
        "Allowed workers/actions:\n"
        f"{available_workers_text(workers)}\n\n"
        f"User request: {user_input}"
    )


async def generate_instruction_with_retry(
    llm_client: LLMClient,
    workers: dict[str, BaseWorker],
    system_prompt: str,
    user_prompt: str,
    user_input: str,
    history: Optional[list[ConversationEntry]],
) -> tuple[Optional[Instruction], str]:
    """生成指令并进行一次纠错重试"""
    llm_response = await llm_client.generate(system_prompt, user_prompt, history=history)
    instruction, error = parse_and_validate_instruction(llm_response, llm_client, workers)
    if instruction:
        return instruction, ""

    repair_prompt = build_repair_prompt(user_input, error, workers)
    llm_response = await llm_client.generate(system_prompt, repair_prompt, history=history)
    instruction, error = parse_and_validate_instruction(llm_response, llm_client, workers)
    if instruction:
        return instruction, ""

    fallback = build_fallback_instruction(user_input, error, workers)
    if fallback:
        return fallback, ""

    return None, error
