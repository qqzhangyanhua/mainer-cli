"""Shell 命令白名单模块 - 命令安全检查逻辑"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional

from src.orchestrator.whitelist_rules import (
    ALLOWED_PIPE_COMMANDS,
    BLOCKED_COMMANDS,
    DANGEROUS_PATTERNS,
    COMMAND_WHITELIST,
    CommandRule,
)
from src.types import RiskLevel


@dataclass
class CommandCheckResult:
    """命令检查结果"""

    allowed: bool  # 是否允许执行
    risk_level: RiskLevel  # 风险等级
    reason: str  # 允许/拒绝原因
    matched_rule: Optional[CommandRule] = None  # 匹配的规则


def parse_command(command: str) -> tuple[str, Optional[str], list[str]]:
    """解析命令，提取基础命令、子命令和参数

    Returns:
        (base_command, subcommand, args)
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.split()[0] if command.split() else "", None, []

    if not tokens:
        return "", None, []

    base_command = tokens[0]

    # 处理路径形式的命令，如 /usr/bin/ls -> ls
    if "/" in base_command:
        base_command = base_command.rsplit("/", 1)[-1]

    subcommand: Optional[str] = None
    args: list[str] = []

    if len(tokens) > 1:
        if base_command in {
            "docker", "docker-compose", "git", "systemctl", "apt", "yum", "npm", "pip"
        }:
            for i, token in enumerate(tokens[1:], 1):
                if not token.startswith("-"):
                    subcommand = token
                    args = tokens[i + 1:]
                    break
            else:
                args = tokens[1:]
        else:
            args = tokens[1:]

    return base_command, subcommand, args


def check_dangerous_patterns(command: str) -> Optional[str]:
    """检查危险模式"""
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            if pattern == "|":
                continue
            return f"Dangerous pattern detected: '{pattern}'"
    return None


def check_pipe_safety(command: str) -> Optional[str]:
    """检查管道命令安全性"""
    if "|" not in command:
        return None

    pipe_parts = command.split("|")

    for part in pipe_parts[1:]:
        part = part.strip()
        if not part:
            continue
        base_cmd, _, _ = parse_command(part)
        if base_cmd not in ALLOWED_PIPE_COMMANDS:
            return (
                f"Command '{base_cmd}' is not allowed in pipe. "
                f"Allowed: {', '.join(sorted(ALLOWED_PIPE_COMMANDS))}"
            )
    return None


def find_matching_rule(
    base_command: str, subcommand: Optional[str]
) -> Optional[CommandRule]:
    """查找匹配的规则"""
    for rule in COMMAND_WHITELIST:
        if rule.base_command == base_command and rule.subcommand == subcommand:
            return rule

    for rule in COMMAND_WHITELIST:
        if rule.base_command == base_command and rule.subcommand is None:
            return rule

    return None


def check_blocked_flags(rule: CommandRule, args: list[str]) -> Optional[str]:
    """检查是否包含禁止的参数"""
    if not rule.blocked_flags:
        return None

    for arg in args:
        for blocked in rule.blocked_flags:
            if arg == blocked or arg.startswith(f"{blocked}="):
                return f"Flag '{blocked}' is not allowed for command '{rule.base_command}'"

            if arg.startswith("-") and not arg.startswith("--"):
                for char in arg[1:]:
                    if f"-{char}" in rule.blocked_flags or char in rule.blocked_flags:
                        return (
                            f"Flag '-{char}' is not allowed for command "
                            f"'{rule.base_command}'"
                        )
    return None


def check_command_safety(command: str) -> CommandCheckResult:
    """检查命令是否安全"""
    command = command.strip()

    if not command:
        return CommandCheckResult(allowed=False, risk_level="high", reason="Empty command")

    # 1. 检查危险模式
    danger_reason = check_dangerous_patterns(command)
    if danger_reason:
        return CommandCheckResult(allowed=False, risk_level="high", reason=danger_reason)

    # 2. 解析命令
    base_command, subcommand, args = parse_command(command)

    # 3. 检查绝对禁止列表
    if base_command in BLOCKED_COMMANDS:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=f"Command '{base_command}' is blocked for security reasons",
        )

    # 4. 查找匹配规则
    rule = find_matching_rule(base_command, subcommand)

    if rule is None:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=(
                f"Command '{base_command}' is not in whitelist. "
                f"Use dedicated Workers for specific tasks."
            ),
        )

    # 5. 检查禁止参数
    flag_reason = check_blocked_flags(rule, args)
    if flag_reason:
        return CommandCheckResult(
            allowed=False, risk_level="high", reason=flag_reason, matched_rule=rule,
        )

    # 6. 检查管道安全性
    pipe_reason = check_pipe_safety(command)
    if pipe_reason:
        return CommandCheckResult(
            allowed=False, risk_level="high", reason=pipe_reason, matched_rule=rule,
        )

    # 7. 通过检查
    return CommandCheckResult(
        allowed=True,
        risk_level=rule.risk_level,
        reason=f"Allowed: {rule.description}",
        matched_rule=rule,
    )


def get_command_risk_level(command: str) -> RiskLevel:
    """获取命令的风险等级"""
    result = check_command_safety(command)
    return result.risk_level
