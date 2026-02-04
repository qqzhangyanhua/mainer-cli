"""安全检查模块 - Orchestrator 集中式拦截"""

from __future__ import annotations

from src.types import Instruction, RiskLevel


# 危险模式定义
DANGER_PATTERNS: dict[str, list[str]] = {
    "high": [
        "rm -rf",
        "kill -9",
        "format",
        "dd if=",
        "> /dev/",
        "mkfs",
        ":(){:|:&};:",  # Fork bomb
        "chmod -R 777",
        "chown -R",
    ],
    "medium": [
        "rm ",
        "kill",
        "docker rm",
        "docker stop",
        "systemctl stop",
        "systemctl restart",
        "reboot",
        "shutdown",
    ],
}


def check_safety(instruction: Instruction) -> RiskLevel:
    """检查指令的安全级别

    安全检查集中在 Orchestrator，不散落在各个 Worker

    Args:
        instruction: 待检查的指令

    Returns:
        RiskLevel: safe | medium | high
    """
    # 将指令转换为可检查的文本
    command_text = _instruction_to_text(instruction)

    # 按风险等级从高到低检查
    for level in ["high", "medium"]:
        patterns = DANGER_PATTERNS.get(level, [])
        for pattern in patterns:
            if pattern in command_text:
                return level  # type: ignore[return-value]

    return "safe"


def _instruction_to_text(instruction: Instruction) -> str:
    """将指令转换为可检查的文本

    Args:
        instruction: 指令对象

    Returns:
        包含动作和参数的文本
    """
    parts = [instruction.action]

    # 递归提取所有字符串值
    def extract_strings(obj: object) -> list[str]:
        strings: list[str] = []
        if isinstance(obj, str):
            strings.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                strings.extend(extract_strings(v))
        elif isinstance(obj, list):
            for item in obj:
                strings.extend(extract_strings(item))
        return strings

    parts.extend(extract_strings(instruction.args))
    return " ".join(parts)
