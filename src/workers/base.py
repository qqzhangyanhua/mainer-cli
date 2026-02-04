"""Worker 抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.types import WorkerResult


class BaseWorker(ABC):
    """所有 Worker 的抽象基类

    Worker 保持"愚蠢"状态，仅负责执行，不负责推理
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Worker 标识符名称"""
        ...

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """返回支持的 action 列表

        用于生成 LLM Prompt，告知 LLM 可用的操作

        Returns:
            支持的动作名称列表
        """
        ...

    @abstractmethod
    async def execute(
        self,
        action: str,
        args: dict[str, str | int | bool | list[str] | dict[str, str]],
    ) -> WorkerResult:
        """执行指定动作

        Args:
            action: 动作名称
            args: 参数字典

        Returns:
            WorkerResult: 执行结果
        """
        ...
