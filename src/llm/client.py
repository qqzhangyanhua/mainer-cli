"""LLM 客户端封装 - 基于 LiteLLM"""

from __future__ import annotations

import json
import re
from typing import Optional

from litellm import acompletion

from src.config.manager import LLMConfig


class LLMClient:
    """LLM 客户端

    封装 LiteLLM，提供统一的 LLM 调用接口
    """

    def __init__(self, config: LLMConfig) -> None:
        """初始化 LLM 客户端

        Args:
            config: LLM 配置
        """
        self._config = config

    @property
    def model(self) -> str:
        """获取模型名称"""
        return self._config.model

    def build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> list[dict[str, str]]:
        """构建消息列表

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示

        Returns:
            消息列表
        """
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """生成 LLM 响应

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示

        Returns:
            LLM 响应文本
        """
        messages = self.build_messages(system_prompt, user_prompt)

        response = await acompletion(
            model=self._config.model,
            messages=messages,
            api_base=self._config.base_url,
            api_key=self._config.api_key or None,
            timeout=self._config.timeout,
            max_tokens=self._config.max_tokens,
        )

        content: str = response.choices[0].message.content or ""
        return content

    def parse_json_response(
        self,
        response: str,
    ) -> Optional[dict[str, object]]:
        """解析 LLM 响应中的 JSON

        支持提取 Markdown 代码块中的 JSON

        Args:
            response: LLM 响应文本

        Returns:
            解析后的字典，解析失败返回 None
        """
        # 尝试提取 Markdown JSON 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.strip()

        try:
            result: dict[str, object] = json.loads(json_str)
            return result
        except json.JSONDecodeError:
            return None
