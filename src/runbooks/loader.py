"""Runbook 加载器 — 根据用户意图检索相关诊断知识"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class DiagnosticStep:
    """诊断步骤"""

    description: str
    command: str
    risk: str = "safe"


@dataclass
class DiagnosticRunbook:
    """诊断 Runbook"""

    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    steps: list[DiagnosticStep] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """转换为 prompt 可注入的上下文文本"""
        lines = [f"## Diagnostic reference: {self.name}"]
        lines.append(self.description)
        lines.append("")
        lines.append("Suggested diagnostic steps (adapt as needed):")
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step.description}")
            lines.append(f"   Command: `{step.command}`")
        return "\n".join(lines)


class RunbookLoader:
    """Runbook 加载器

    从 YAML 文件加载诊断 Runbook，并根据用户输入匹配相关的 Runbook。
    """

    def __init__(self, runbook_dir: Optional[Path] = None) -> None:
        if runbook_dir is None:
            runbook_dir = Path(__file__).parent / "data"
        self._runbook_dir = runbook_dir
        self._runbooks: dict[str, DiagnosticRunbook] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """延迟加载所有 Runbook"""
        if self._loaded:
            return
        self._loaded = True

        if not self._runbook_dir.exists():
            return

        for yaml_file in self._runbook_dir.glob("*.yaml"):
            try:
                runbook = self._load_file(yaml_file)
                if runbook:
                    self._runbooks[runbook.name] = runbook
            except Exception:
                continue

    @staticmethod
    def _load_file(path: Path) -> Optional[DiagnosticRunbook]:
        """从 YAML 文件加载单个 Runbook"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return None

        steps: list[DiagnosticStep] = []
        for step_data in data.get("steps", []):
            if isinstance(step_data, dict):
                steps.append(DiagnosticStep(
                    description=str(step_data.get("description", "")),
                    command=str(step_data.get("command", "")),
                    risk=str(step_data.get("risk", "safe")),
                ))

        return DiagnosticRunbook(
            name=str(data.get("name", path.stem)),
            description=str(data.get("description", "")),
            keywords=data.get("keywords", []),
            steps=steps,
        )

    def match(self, user_input: str, top_k: int = 2) -> list[DiagnosticRunbook]:
        """根据用户输入匹配相关 Runbook

        使用关键词匹配（轻量级，无需向量数据库）。
        """
        self._ensure_loaded()

        input_lower = user_input.lower()
        scored: list[tuple[int, DiagnosticRunbook]] = []

        for runbook in self._runbooks.values():
            score = 0
            for keyword in runbook.keywords:
                if keyword.lower() in input_lower:
                    score += 1
            if score > 0:
                scored.append((score, runbook))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [rb for _, rb in scored[:top_k]]

    def get(self, name: str) -> Optional[DiagnosticRunbook]:
        """按名称获取 Runbook"""
        self._ensure_loaded()
        return self._runbooks.get(name)

    def list_all(self) -> list[DiagnosticRunbook]:
        """列出所有可用 Runbook"""
        self._ensure_loaded()
        return list(self._runbooks.values())
