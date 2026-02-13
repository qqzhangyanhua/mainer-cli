"""安全检查模块 - Orchestrator 集中式拦截

向后兼容层：DANGER_PATTERNS 和 check_safety 的原有导入路径保持不变。
实际逻辑已迁移到 PolicyEngine。
"""

from __future__ import annotations

from src.orchestrator.policy_engine import (
    DANGER_PATTERNS,
    PolicyEngine,
    _instruction_to_text,
)
from src.types import Instruction, RiskLevel

# 向后兼容：保持 from src.orchestrator.safety import DANGER_PATTERNS 可用
__all__ = ["DANGER_PATTERNS", "check_safety", "_instruction_to_text"]


def check_safety(instruction: Instruction) -> RiskLevel:
    """检查指令的安全级别

    安全检查集中在 Orchestrator，不散落在各个 Worker

    Args:
        instruction: 待检查的指令

    Returns:
        RiskLevel: safe | medium | high
    """
    result = PolicyEngine.check_instruction(instruction)
    return result.risk_level
