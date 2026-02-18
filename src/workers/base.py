"""Worker 抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.types import ActionParam, ArgValue, ToolAction, WorkerResult


class BaseWorker(ABC):
    """所有 Worker 的抽象基类

    Worker 保持"愚蠢"状态，仅负责执行，不负责推理。
    通过 description 和 get_actions() 实现自文档化，
    供 PromptBuilder 和 Function Calling 动态生成工具描述。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Worker 标识符名称"""
        ...

    @property
    def description(self) -> str:
        """Worker 功能描述（供 LLM 理解何时使用此 Worker）

        子类应覆盖此属性提供具体描述。
        """
        return ""

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """返回支持的 action 名称列表

        Returns:
            支持的动作名称列表
        """
        ...

    def get_actions(self) -> list[ToolAction]:
        """返回支持的 action 列表及其参数描述

        子类应覆盖此方法提供详细的 action 描述和参数 schema，
        用于动态生成 LLM prompt 中的工具说明和 Function Calling schema。
        默认实现从 get_capabilities() 生成空描述。

        Returns:
            ToolAction 列表
        """
        return [
            ToolAction(name=cap, description="", params=[])
            for cap in self.get_capabilities()
        ]

    def get_tool_schema(self) -> list[dict[str, object]]:
        """生成 OpenAI Function Calling 格式的 tool schema

        Returns:
            OpenAI tools 数组中的 function 定义列表
        """
        schemas: list[dict[str, object]] = []
        for action in self.get_actions():
            properties: dict[str, dict[str, str]] = {}
            required: list[str] = []
            for param in action.params:
                prop: dict[str, str] = {
                    "type": _map_param_type(param.param_type),
                    "description": param.description,
                }
                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            function_def: dict[str, object] = {
                "type": "function",
                "function": {
                    "name": f"{self.name}__{action.name}",
                    "description": action.description or f"{self.name}.{action.name}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            schemas.append(function_def)
        return schemas

    @abstractmethod
    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行指定动作

        Args:
            action: 动作名称
            args: 参数字典

        Returns:
            WorkerResult: 执行结果
        """
        ...


def _map_param_type(param_type: str) -> str:
    """将内部参数类型映射到 JSON Schema 类型"""
    mapping = {
        "string": "string",
        "integer": "integer",
        "boolean": "boolean",
        "array": "array",
        "number": "number",
    }
    return mapping.get(param_type, "string")
