"""LLM 客户端封装 - 基于 OpenAI SDK"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, cast

from openai import AsyncOpenAI

from src.config.manager import LLMConfig
from src.llm.token_budget import TokenBudgetExceededError, TokenBudgetManager
from src.types import ArgValue, ConversationEntry, get_raw_output, is_output_truncated

if TYPE_CHECKING:
    from src.workers.base import BaseWorker


logger = logging.getLogger(__name__)


@dataclass
class ToolCallResult:
    """Function Calling 解析结果"""

    worker: str
    action: str
    args: dict[str, ArgValue]
    thinking: str = ""
    is_final: bool = False
    raw_content: str = ""


class LLMClient:
    """LLM 客户端

    封装 OpenAI SDK，提供统一的 LLM 调用接口。
    支持两种模式：
    - 文本模式（generate）：LLM 输出 JSON 文本，手动解析
    - Function Calling 模式（generate_with_tools）：LLM 原生调用工具
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "dummy-key",
            timeout=float(config.timeout),
        )
        self._budget_manager = TokenBudgetManager.from_config(config)

    @property
    def model(self) -> str:
        """获取模型名称"""
        return self._config.model

    @property
    def supports_function_calling(self) -> bool:
        """模型是否支持 Function Calling"""
        return self._config.supports_function_calling

    def build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[list[ConversationEntry]] = None,
    ) -> list[dict[str, str]]:
        """构建消息列表

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            history: 对话历史（用于构建多轮对话）

        Returns:
            消息列表
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # 将历史记录转换为标准的多轮对话格式
        if history:
            for entry in history:
                # 用户消息
                if entry.user_input:
                    messages.append({"role": "user", "content": entry.user_input})
                # 助手回复（使用 worker 执行结果）
                assistant_content = entry.result.message
                raw_output = get_raw_output(entry.result)
                if raw_output:
                    truncated = is_output_truncated(entry.result)
                    note = " [OUTPUT TRUNCATED]" if truncated else ""
                    assistant_content += f"\n\nRaw Output{note}:\n{raw_output}"
                messages.append({"role": "assistant", "content": assistant_content})

        # 当前用户输入
        messages.append({"role": "user", "content": user_prompt})

        return messages

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[list[ConversationEntry]] = None,
    ) -> str:
        """生成 LLM 响应

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            history: 对话历史（用于构建多轮对话）

        Returns:
            LLM 响应文本
        """
        messages = self.build_messages(system_prompt, user_prompt, history)

        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,  # type: ignore
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )

        self._handle_usage(response.usage)

        content: str = response.choices[0].message.content or ""
        return content

    @staticmethod
    def build_tool_schemas(workers: dict[str, BaseWorker]) -> list[dict[str, object]]:
        """从 Worker 元数据生成 OpenAI Function Calling tool schemas"""
        schemas: list[dict[str, object]] = []
        for worker in workers.values():
            schemas.extend(worker.get_tool_schema())
        return schemas

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        workers: dict[str, BaseWorker],
        history: Optional[list[ConversationEntry]] = None,
    ) -> Optional[ToolCallResult]:
        """使用 Function Calling 生成 LLM 响应

        Returns:
            ToolCallResult 或 None（解析失败时）
        """
        messages = self.build_messages(system_prompt, user_prompt, history)
        tools = self.build_tool_schemas(workers)

        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,  # type: ignore
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            tools=tools,  # type: ignore
        )

        self._handle_usage(response.usage)

        message = response.choices[0].message
        content = message.content or ""

        # 检查是否有 tool_calls
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            tool_function = getattr(tool_call, "function", None)
            if tool_function is None:
                return None
            func_name = str(getattr(tool_function, "name", ""))
            try:
                func_args_raw = getattr(tool_function, "arguments", "{}")
                func_args = json.loads(func_args_raw)
            except json.JSONDecodeError:
                func_args = {}

            # 解析 worker__action 格式
            if "__" in func_name:
                worker_name, action_name = func_name.split("__", 1)
            else:
                worker_name = func_name
                action_name = ""

            # 检查是否为最终回复
            is_final = worker_name == "chat" and action_name == "respond"

            return ToolCallResult(
                worker=worker_name,
                action=action_name,
                args=func_args,
                thinking=content,
                is_final=is_final,
                raw_content=content,
            )

        # 没有 tool_calls，尝试从 content 解析（fallback）
        if content:
            parsed = self.parse_json_response(content)
            if parsed:
                return self._parsed_json_to_tool_call(parsed)

        return None

    def _handle_usage(self, usage: Optional[object]) -> None:
        if usage is None:
            return

        total_tokens = getattr(usage, "total_tokens", None)
        if not isinstance(total_tokens, int):
            return

        status = self._budget_manager.track_usage(total_tokens)
        if status is None:
            return

        if status.exceeded:
            raise TokenBudgetExceededError(f"Token 预算已超限: {status.used}/{status.limit}")
        if status.warning:
            logger.warning("Token usage warning: %s/%s", status.used, status.limit)

    @staticmethod
    def _parsed_json_to_tool_call(parsed: dict[str, object]) -> Optional[ToolCallResult]:
        """将解析的 JSON 转换为 ToolCallResult（兼容旧格式）"""
        thinking = str(parsed.get("thinking", ""))
        is_final = bool(parsed.get("is_final", False))

        action_dict = parsed.get("action")
        inst = action_dict if isinstance(action_dict, dict) and "worker" in action_dict else parsed

        worker = str(inst.get("worker", ""))
        action = str(inst.get("action", ""))
        args_value = inst.get("args", {})
        args = cast(dict[str, ArgValue], args_value) if isinstance(args_value, dict) else {}

        if not worker or not action:
            return None

        return ToolCallResult(
            worker=worker,
            action=action,
            args=args,
            thinking=thinking,
            is_final=is_final,
        )

    def parse_json_response(
        self,
        response: str,
    ) -> Optional[dict[str, object]]:
        """解析 LLM 响应中的 JSON

        支持提取 Markdown 代码块中的 JSON，并尝试修复常见格式问题

        Args:
            response: LLM 响应文本

        Returns:
            解析后的字典，解析失败返回 None
        """
        # 尝试提取 Markdown JSON 代码块（支持多种格式）
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        json_str = json_match.group(1).strip() if json_match else response.strip()

        # 尝试直接解析
        try:
            result: dict[str, object] = json.loads(json_str)
            return result
        except json.JSONDecodeError:
            pass

        # 尝试修复常见问题
        # 1. 提取第一个完整的 JSON 对象（处理多余的 } 或尾部垃圾）
        brace_count = 0
        start_idx = -1
        end_idx = -1

        for i, char in enumerate(json_str):
            if char == "{":
                if start_idx == -1:
                    start_idx = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break

        if start_idx != -1 and end_idx != -1:
            try:
                fixed_json = json_str[start_idx:end_idx]
                result = json.loads(fixed_json)
                return result
            except json.JSONDecodeError:
                pass

        # 2. 尝试从原始响应中提取（不仅仅是代码块）
        brace_count = 0
        start_idx = -1
        end_idx = -1

        for i, char in enumerate(response):
            if char == "{":
                if start_idx == -1:
                    start_idx = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break

        if start_idx != -1 and end_idx != -1:
            try:
                fixed_json = response[start_idx:end_idx]
                result = json.loads(fixed_json)
                return result
            except json.JSONDecodeError:
                pass

        return None
