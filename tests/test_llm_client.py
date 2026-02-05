"""LLM 客户端测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.manager import LLMConfig
from src.llm.client import LLMClient


class TestLLMClient:
    """测试 LLM 客户端"""

    def test_client_initialization(self) -> None:
        """测试客户端初始化"""
        config = LLMConfig(model="test-model", api_key="test-key")
        client = LLMClient(config)

        assert client.model == "test-model"

    def test_build_messages(self) -> None:
        """测试消息构建"""
        config = LLMConfig()
        client = LLMClient(config)

        messages = client.build_messages(
            system_prompt="You are helpful",
            user_prompt="Hello",
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_generate_calls_openai(self) -> None:
        """测试生成调用 OpenAI SDK"""
        config = LLMConfig(model="test-model")
        client = LLMClient(config)

        mock_message = MagicMock()
        mock_message.content = '{"worker": "system", "action": "test"}'

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            client._client.chat.completions,
            "create",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_response

            result = await client.generate(
                system_prompt="System",
                user_prompt="User",
            )

            assert result == '{"worker": "system", "action": "test"}'
            mock_create.assert_called_once()

    def test_parse_json_response_valid(self) -> None:
        """测试解析有效 JSON"""
        config = LLMConfig()
        client = LLMClient(config)

        response = '{"worker": "system", "action": "test", "args": {}}'
        result = client.parse_json_response(response)

        assert result is not None
        assert result["worker"] == "system"
        assert result["action"] == "test"

    def test_parse_json_response_with_markdown(self) -> None:
        """测试解析带 Markdown 的 JSON"""
        config = LLMConfig()
        client = LLMClient(config)

        response = """Here is the response:
```json
{"worker": "system", "action": "test"}
```"""
        result = client.parse_json_response(response)

        assert result is not None
        assert result["worker"] == "system"

    def test_parse_json_response_invalid(self) -> None:
        """测试解析无效 JSON"""
        config = LLMConfig()
        client = LLMClient(config)

        response = "This is not JSON"
        result = client.parse_json_response(response)

        assert result is None
