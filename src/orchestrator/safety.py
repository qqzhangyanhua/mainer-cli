"""安全检查模块 - Orchestrator 集中式拦截"""

from __future__ import annotations

from src.orchestrator.command_whitelist import check_command_safety
from src.types import Instruction, RiskLevel

# 危险模式定义（用于非 shell 命令的通用检查）
DANGER_PATTERNS: dict[str, list[str]] = {
    "high": [
        "rm -rf",
        "kill -9",
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
        "kill",
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


def check_safety(instruction: Instruction) -> RiskLevel:
    """检查指令的安全级别

    安全检查集中在 Orchestrator，不散落在各个 Worker

    Args:
        instruction: 待检查的指令

    Returns:
        RiskLevel: safe | medium | high
    """
    # 对 Shell 命令使用白名单精确检查
    if instruction.worker == "shell" and instruction.action == "execute_command":
        command = instruction.args.get("command", "")
        if isinstance(command, str) and command:
            result = check_command_safety(command)
            if not result.allowed:
                return "high"  # 不在白名单的命令视为高风险
            return result.risk_level

    # 其他 Worker 使用模式匹配检查
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
