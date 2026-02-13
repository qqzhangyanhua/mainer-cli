"""LLM 客户端封装 - 基于 OpenAI SDK"""

from __future__ import annotations

import json
import re
from typing import Optional

from openai import AsyncOpenAI

from src.config.manager import LLMConfig
from src.types import ConversationEntry, get_raw_output, is_output_truncated


class LLMClient:
    """LLM 客户端

    封装 OpenAI SDK，提供统一的 LLM 调用接口
    直接使用 OpenAI 标准 API 格式 (/v1/chat/completions)
    """

    def __init__(self, config: LLMConfig) -> None:
        """初始化 LLM 客户端

        Args:
            config: LLM 配置
        """
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "dummy-key",  # 某些兼容 API 不需要 key
            timeout=float(config.timeout),
        )

    @property
    def model(self) -> str:
        """获取模型名称"""
        return self._config.model

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

        content: str = response.choices[0].message.content or ""
        return content

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
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.strip()

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
