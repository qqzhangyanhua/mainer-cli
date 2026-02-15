"""统一安全策略引擎 - 合并白名单 + 规则引擎的两步检查为一步"""

from __future__ import annotations

from dataclasses import dataclass

from src.orchestrator.command_whitelist import CommandCheckResult, check_command_safety
from src.orchestrator.risk_analyzer import analyze_command_risk
from src.types import Instruction, RiskLevel

# 危险模式定义（用于非 shell 命令的通用检查）
DANGER_PATTERNS: dict[str, list[str]] = {
    "high": [
        "rm -rf",
        "kill",
        "mkfs",  # 磁盘格式化
        "dd if=",
        "> /dev/",
        ":(){:|:&};:",  # Fork bomb
        "chmod -R 777",
        "chown -R",
        "delete_files",  # SystemWorker 删除文件操作
        "replace_in_file",  # SystemWorker 文件替换操作
    ],
    "medium": [
        "rm ",
        "docker rm",
        "docker stop",
        "systemctl stop",
        "systemctl restart",
        "reboot",
        "shutdown",
        "restart",  # 容器重启
        "stop",  # 容器停止
        "write_file",  # SystemWorker 写入文件
        "append_to_file",  # SystemWorker 追加内容
    ],
}


def _instruction_to_text(instruction: Instruction) -> str:
    """将指令转换为可检查的文本

    Args:
        instruction: 指令对象

    Returns:
        包含动作和参数的文本
    """
    parts = [instruction.action]

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


@dataclass
class PolicyResult:
    """指令级安全检查结果"""

    risk_level: RiskLevel
    allowed: bool
    reason: str


class PolicyEngine:
    """统一安全策略入口

    合并白名单快速通道 + 规则引擎兜底为统一接口，
    消除 safety_node 和 ShellWorker.execute 各验证一次的重复逻辑。
    """

    @staticmethod
    def check_instruction(instruction: Instruction) -> PolicyResult:
        """检查指令的安全级别

        对 Shell 命令使用 check_command 统一检查，
        对其他 Worker 使用模式匹配。
        远程执行命令最低为 medium 风险。

        Args:
            instruction: 待检查的指令

        Returns:
            PolicyResult: 包含 risk_level, allowed, reason
        """
        # Shell 命令走白名单 + 规则引擎统一通道
        if instruction.worker == "shell" and instruction.action == "execute_command":
            command = instruction.args.get("command", "")
            if isinstance(command, str) and command:
                cmd_result = PolicyEngine.check_command(command)
                risk = cmd_result.risk_level or "medium"
                return PolicyResult(
                    risk_level=risk,
                    allowed=cmd_result.allowed is not False,
                    reason=cmd_result.reason,
                )

        # 远程执行命令：最低 medium 风险
        if instruction.worker == "remote" and instruction.action == "execute":
            command = instruction.args.get("command", "")
            command_text = _instruction_to_text(instruction)
            risk: RiskLevel = "medium"
            reason = "Remote execution: minimum medium risk"

            # 检查是否包含高危模式
            for pattern in DANGER_PATTERNS.get("high", []):
                if pattern in command_text:
                    risk = "high"
                    reason = f"Remote high-risk pattern: '{pattern}'"
                    break

            return PolicyResult(risk_level=risk, allowed=True, reason=reason)

        # 其他 Worker 使用模式匹配
        command_text = _instruction_to_text(instruction)

        for level in ["high", "medium"]:
            patterns = DANGER_PATTERNS.get(level, [])
            for pattern in patterns:
                if pattern in command_text:
                    return PolicyResult(
                        risk_level=level,  # type: ignore[arg-type]
                        allowed=True,
                        reason=f"Pattern matched: '{pattern}'",
                    )

        return PolicyResult(risk_level="safe", allowed=True, reason="No dangerous pattern found")

    @staticmethod
    def check_command(command: str) -> CommandCheckResult:
        """检查 shell 命令安全性（合并白名单 + 规则引擎为一步）

        Args:
            command: 待检查的 shell 命令

        Returns:
            CommandCheckResult: 最终检查结果
        """
        result = check_command_safety(command)

        if result.allowed is not None:
            # 白名单明确判定（允许或拒绝），直接返回
            return result

        # 白名单未匹配 → 规则引擎接管
        return analyze_command_risk(command)
