"""LLM 模型预设配置"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelPreset:
    """模型预设"""

    name: str
    model: str
    base_url: str
    description: str
    requires_api_key: bool = True
    supports_function_calling: bool = False
    context_window: int = 8192
    recommended_max_tokens: int = 2048
    recommended_temperature: float = 0.2


MODEL_PRESETS: dict[str, ModelPreset] = {
    "local-qwen": ModelPreset(
        name="local-qwen",
        model="qwen2.5:7b",
        base_url="http://localhost:11434/v1",
        description="本地 Qwen 2.5 7B (Ollama)",
        requires_api_key=False,
        supports_function_calling=False,
        context_window=32768,
        recommended_max_tokens=2048,
    ),
    "local-qwen-32b": ModelPreset(
        name="local-qwen-32b",
        model="qwen2.5:32b",
        base_url="http://localhost:11434/v1",
        description="本地 Qwen 2.5 32B (Ollama，需要 32GB+ 内存)",
        requires_api_key=False,
        supports_function_calling=False,
        context_window=32768,
        recommended_max_tokens=4096,
    ),
    "openai-gpt4o": ModelPreset(
        name="openai-gpt4o",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        description="OpenAI GPT-4o (推荐，推理能力强)",
        requires_api_key=True,
        supports_function_calling=True,
        context_window=128000,
        recommended_max_tokens=4096,
    ),
    "openai-gpt4o-mini": ModelPreset(
        name="openai-gpt4o-mini",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        description="OpenAI GPT-4o Mini (性价比高)",
        requires_api_key=True,
        supports_function_calling=True,
        context_window=128000,
        recommended_max_tokens=4096,
    ),
    "deepseek": ModelPreset(
        name="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        description="DeepSeek Chat (国产，性价比极高)",
        requires_api_key=True,
        supports_function_calling=True,
        context_window=64000,
        recommended_max_tokens=4096,
    ),
    "qwen-max": ModelPreset(
        name="qwen-max",
        model="qwen-max",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="阿里云 Qwen-Max (推理能力强)",
        requires_api_key=True,
        supports_function_calling=True,
        context_window=32768,
        recommended_max_tokens=4096,
    ),
    "claude-sonnet": ModelPreset(
        name="claude-sonnet",
        model="claude-sonnet-4-20250514",
        base_url="https://api.anthropic.com/v1",
        description="Anthropic Claude Sonnet (需 OpenAI 兼容代理)",
        requires_api_key=True,
        supports_function_calling=True,
        context_window=200000,
        recommended_max_tokens=4096,
    ),
}


def get_preset(name: str) -> Optional[ModelPreset]:
    """获取模型预设"""
    return MODEL_PRESETS.get(name)


def list_presets() -> list[ModelPreset]:
    """列出所有模型预设"""
    return list(MODEL_PRESETS.values())
