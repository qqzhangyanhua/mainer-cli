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

    allowed: Optional[bool]  # 是否允许执行（None=未匹配，交由规则引擎判定）
    risk_level: Optional[RiskLevel]  # 风险等级（None=未匹配时无等级）
    reason: str  # 允许/拒绝原因
    matched_rule: Optional[CommandRule] = None  # 匹配的规则
    matched_by: str = "whitelist"  # 匹配来源: "whitelist" | "risk_analyzer" | "none"


def _extract_subcommand_and_args(
    tokens: list[str], start_index: int
) -> tuple[Optional[str], list[str]]:
    """从 token 列表中提取子命令和参数"""
    for i, token in enumerate(tokens[start_index:], start_index):
        if not token.startswith("-"):
            return token, tokens[i + 1 :]
    return None, tokens[start_index:]


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
        # 兼容 docker compose 语法，统一为 docker-compose 规则匹配
        if base_command == "docker" and tokens[1] == "compose":
            base_command = "docker-compose"
            subcommand, args = _extract_subcommand_and_args(tokens, 2)
        elif base_command in {
            "docker",
            "docker-compose",
            "git",
            "systemctl",
            "apt",
            "apt-get",
            "yum",
            "dnf",
            "brew",
            "npm",
            "yarn",
            "pnpm",
            "pip",
            "pip3",
            "kubectl",
            "helm",
        }:
            subcommand, args = _extract_subcommand_and_args(tokens, 1)
        else:
            args = tokens[1:]

    return base_command, subcommand, args


def split_chain_commands(command: str) -> list[str]:
    """拆分 && 和 || 命令链，尊重引号

    例如:
        "nginx -t && nginx -s reload" → ["nginx -t", "nginx -s reload"]
        'echo "hello && world" && ls' → ['echo "hello && world"', "ls"]
        "simple command" → ["simple command"]

    Returns:
        子命令列表（至少一个元素）
    """
    parts: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(command):
        char = command[i]

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
        elif not in_single_quote and not in_double_quote:
            if i + 1 < len(command) and command[i : i + 2] in ("&&", "||"):
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 2
                continue
            current.append(char)
        else:
            current.append(char)

        i += 1

    part = "".join(current).strip()
    if part:
        parts.append(part)

    return parts if parts else [command]


def check_redirect_safety(command: str) -> Optional[str]:
    """检查重定向安全性

    允许安全的重定向模式（stderr 抑制、流合并）：
        - 2>/dev/null, >/dev/null, 2>>/dev/null  → 丢弃输出
        - 2>&1, >&2                               → 流合并

    拦截危险的文件写入重定向：
        - > file, >> file                          → 用 system.write_file 替代

    Returns:
        拒绝原因字符串，安全则返回 None
    """
    import re

    # 移除引号内容，避免误判（如 grep ">" file）
    cleaned = re.sub(r"'[^']*'", "", command)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)

    # 移除安全的重定向模式
    safe_redirects = [
        r"\d*>{1,2}\s*/dev/null",  # 2>/dev/null, >/dev/null, >>/dev/null
        r"\d*>&\d+",  # 2>&1, >&2
    ]
    for pattern in safe_redirects:
        cleaned = re.sub(pattern, " ", cleaned)

    # 移除安全模式后，检查是否还有残留的重定向
    if re.search(r">{1,2}", cleaned):
        return (
            "File redirect (> or >>) is not allowed. "
            "Redirect to /dev/null is OK (e.g., 2>/dev/null). "
            "To write files, use system.write_file."
        )

    if "<" in cleaned:
        return "Input redirect (<) is not allowed."

    return None


def check_dangerous_patterns(command: str) -> Optional[str]:
    """检查危险模式

    echo 命令允许 $() 和重定向（用于生成配置文件），
    由 _check_echo_safety 在规则匹配后单独校验。

    注意：&&、||、>、>>、< 不在 DANGEROUS_PATTERNS 中，
    由 split_chain_commands 和 check_redirect_safety 智能处理。
    """
    command_stripped = command.strip()

    # echo 命令跳过通用危险模式检查，由 _check_echo_safety 单独处理
    if command_stripped.startswith("echo "):
        return None

    # 其他命令：正常检查所有危险模式
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            if pattern == "|":
                continue
            # & 需要智能处理：排除 && (命令链) 和 >& (重定向合并)
            if pattern == "&":
                if not _has_standalone_ampersand(command):
                    continue
            return f"Dangerous pattern detected: '{pattern}'"
    return None


def _has_standalone_ampersand(command: str) -> bool:
    """检查命令中是否包含独立的 & (后台执行)

    排除以下安全场景：
    - && 命令链（由 split_chain_commands 处理）
    - 2>&1, >&2 等重定向流合并
    """
    import re

    # 移除引号内容
    temp = re.sub(r"'[^']*'", "", command)
    temp = re.sub(r'"[^"]*"', "", temp)
    # 移除重定向流合并模式：2>&1, >&2, 1>&2 等
    temp = re.sub(r"\d*>&\d+", "", temp)
    # 移除 &&（由 split_chain_commands 处理）
    temp = temp.replace("&&", "")
    # 剩余内容中如果还有 & 则是后台执行
    return "&" in temp


def _check_echo_safety(command: str) -> Optional[str]:
    """echo 命令专属安全校验

    echo 允许 $() 和重定向（用于生成配置文件），
    但禁止写入系统关键目录和链式命令。

    Args:
        command: echo 命令字符串

    Returns:
        拒绝原因字符串，安全则返回 None
    """
    import re as _re

    # 检查重定向目标路径
    dangerous_write_paths = [
        "/etc/",
        "/sys/",
        "/proc/",
        "/dev/",
        "/root/",
        "/boot/",
        "/usr/",
        "/var/",
        "/bin/",
        "/sbin/",
        "/lib/",
    ]

    redirect_match = _re.search(r">\s*([/\w.-]+)", command)
    if redirect_match:
        redirect_target = redirect_match.group(1)
        for dangerous_path in dangerous_write_paths:
            if redirect_target.startswith(dangerous_path):
                return f"Dangerous file path detected: '{dangerous_path}'"

    # 检查危险的链式命令模式
    dangerous_for_echo = ["&&", "||", ";", "`", "&", "\\n", "\\r", "${"]
    for pattern in dangerous_for_echo:
        if pattern in command:
            return f"Dangerous pattern detected: '{pattern}'"

    return None


def check_pipe_safety(command: str) -> Optional[str]:
    """检查管道命令安全性

    除了检查管道后的直接命令是否在允许列表中，
    还需要检查 xargs 等命令包装的实际执行命令是否安全。
    例如 `lsof -ti :8080 | xargs kill -9` 中 kill 是高危命令。
    """
    if "|" not in command:
        return None

    pipe_parts = command.split("|")

    for part in pipe_parts[1:]:
        part = part.strip()
        if not part:
            continue
        base_cmd, _, args = parse_command(part)
        if base_cmd not in ALLOWED_PIPE_COMMANDS:
            return (
                f"Command '{base_cmd}' is not allowed in pipe. "
                f"Allowed: {', '.join(sorted(ALLOWED_PIPE_COMMANDS))}"
            )

        # xargs 特殊处理：检查 xargs 实际执行的命令是否安全
        if base_cmd == "xargs" and args:
            # 跳过 xargs 自身的选项（如 -0, -I, -n 等），找到实际命令
            actual_cmd_parts: list[str] = []
            skip_next = False
            for arg in args:
                if skip_next:
                    skip_next = False
                    continue
                # xargs 带参数的选项
                if arg in ("-I", "-n", "-P", "-L", "-s", "-d"):
                    skip_next = True
                    continue
                if arg.startswith("-"):
                    continue
                actual_cmd_parts.append(arg)

            if actual_cmd_parts:
                actual_cmd = actual_cmd_parts[0]
                # 检查 xargs 执行的命令是否在禁止列表中
                if actual_cmd in BLOCKED_COMMANDS:
                    return (
                        f"Command '{actual_cmd}' via xargs is blocked for security reasons"
                    )

    return None


def check_xargs_risk(command: str) -> Optional[RiskLevel]:
    """检查管道中 xargs 实际执行命令的风险等级

    例如 `lsof -ti :8080 | xargs kill -9` 中，kill 是高危命令，
    需要提升整个命令的风险等级以触发用户确认。

    Args:
        command: 完整命令字符串

    Returns:
        如果 xargs 执行的是高危命令则返回对应 RiskLevel，否则返回 None
    """
    if "|" not in command:
        return None

    pipe_parts = command.split("|")

    for part in pipe_parts[1:]:
        part = part.strip()
        if not part:
            continue
        base_cmd, _, args = parse_command(part)

        if base_cmd == "xargs" and args:
            actual_cmd_parts: list[str] = []
            skip_next = False
            for arg in args:
                if skip_next:
                    skip_next = False
                    continue
                if arg in ("-I", "-n", "-P", "-L", "-s", "-d"):
                    skip_next = True
                    continue
                if arg.startswith("-"):
                    continue
                actual_cmd_parts.append(arg)

            if actual_cmd_parts:
                actual_full = " ".join(actual_cmd_parts)
                from src.orchestrator.policy_engine import DANGER_PATTERNS

                for level in ["high", "medium"]:
                    for pattern in DANGER_PATTERNS.get(level, []):
                        if pattern in actual_full:
                            return level  # type: ignore[return-value]

    return None


def find_matching_rule(base_command: str, subcommand: Optional[str]) -> Optional[CommandRule]:
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
                        return f"Flag '-{char}' is not allowed for command '{rule.base_command}'"
    return None


def _check_chain_safety(sub_commands: list[str]) -> CommandCheckResult:
    """检查命令链（&& / ||）中每个子命令的安全性

    策略：
    - 任意子命令被拦截 → 整条链被拦截
    - 任意子命令未匹配白名单 → 整条链交给风险分析引擎
    - 全部通过 → 取最高风险等级
    """
    results = [_check_single_command_safety(cmd) for cmd in sub_commands]

    risk_order: dict[Optional[RiskLevel], int] = {
        "safe": 0, "medium": 1, "high": 2, None: 1,
    }

    # 任一子命令被显式拦截 → 整条链拦截
    for r in results:
        if r.allowed is False:
            return CommandCheckResult(
                allowed=False,
                risk_level=r.risk_level or "high",
                reason=f"Command in chain blocked: {r.reason}",
            )

    # 任一子命令未匹配白名单 → 交给风险分析引擎
    for r in results:
        if r.allowed is None:
            return CommandCheckResult(
                allowed=None,
                risk_level=None,
                reason=f"Command in chain not matched: {r.reason}",
                matched_by="none",
            )

    # 全部通过：取最高风险
    highest = max(results, key=lambda r: risk_order.get(r.risk_level, 1))
    return CommandCheckResult(
        allowed=True,
        risk_level=highest.risk_level,
        reason=f"Chain of {len(sub_commands)} commands allowed",
        matched_rule=highest.matched_rule,
    )


def _check_single_command_safety(command: str) -> CommandCheckResult:
    """检查单条命令的安全性（不含 && / ||）"""
    # 1. 检查危险模式（;、$()、`、& 等）
    danger_reason = check_dangerous_patterns(command)
    if danger_reason:
        return CommandCheckResult(allowed=False, risk_level="high", reason=danger_reason)

    # 1.5 检查重定向安全性（允许 2>/dev/null，拦截文件写入）
    # echo 命令跳过通用重定向检查，由 _check_echo_safety 单独处理
    if not command.strip().startswith("echo "):
        redirect_reason = check_redirect_safety(command)
        if redirect_reason:
            return CommandCheckResult(
                allowed=False, risk_level="high", reason=redirect_reason
            )

    # 2. 解析命令
    base_command, subcommand, args = parse_command(command)

    # 3. 检查绝对禁止列表（支持前缀匹配，如 mkfs.ext4 → mkfs）
    blocked_match = base_command in BLOCKED_COMMANDS
    if not blocked_match:
        base_prefix = base_command.split(".")[0] if "." in base_command else ""
        blocked_match = base_prefix in BLOCKED_COMMANDS
    if blocked_match:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=f"Command '{base_command}' is blocked for security reasons",
        )

    # 4. 查找匹配规则
    rule = find_matching_rule(base_command, subcommand)

    if rule is None:
        info_only_flags = {"--version", "--help", "-v", "-V", "-h", "version", "help"}
        all_args = ([subcommand] if subcommand else []) + args
        if all_args and all(a in info_only_flags for a in all_args):
            has_any_rule = any(r.base_command == base_command for r in COMMAND_WHITELIST)
            if has_any_rule:
                return CommandCheckResult(
                    allowed=True,
                    risk_level="safe",
                    reason=f"Allowed: {base_command} version/help query",
                )

        return CommandCheckResult(
            allowed=None,
            risk_level=None,
            reason=f"Command '{base_command}' not matched in whitelist",
            matched_by="none",
        )

    # 5. 检查禁止参数
    flag_reason = check_blocked_flags(rule, args)
    if flag_reason:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=flag_reason,
            matched_rule=rule,
        )

    # 6. 检查管道安全性
    pipe_reason = check_pipe_safety(command)
    if pipe_reason:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=pipe_reason,
            matched_rule=rule,
        )

    # 7. echo 命令额外校验（重定向目标 + 链式命令）
    if base_command == "echo":
        echo_reason = _check_echo_safety(command)
        if echo_reason:
            return CommandCheckResult(
                allowed=False,
                risk_level="high",
                reason=echo_reason,
                matched_rule=rule,
            )

    # 8. 检查 xargs 包装的实际命令风险（如 xargs kill -9）
    xargs_risk = check_xargs_risk(command)
    if xargs_risk is not None:
        return CommandCheckResult(
            allowed=True,
            risk_level=xargs_risk,
            reason="Allowed but risk elevated: xargs wraps dangerous command",
            matched_rule=rule,
        )

    # 9. 通过检查
    return CommandCheckResult(
        allowed=True,
        risk_level=rule.risk_level,
        reason=f"Allowed: {rule.description}",
        matched_rule=rule,
    )


def check_command_safety(command: str) -> CommandCheckResult:
    """检查命令是否安全

    支持 && / || 命令链：自动拆分后独立检查每个子命令。
    支持安全重定向：2>/dev/null、2>&1 等不被拦截。
    """
    command = command.strip()

    if not command:
        return CommandCheckResult(allowed=False, risk_level="high", reason="Empty command")

    # 0. 拆分命令链（&& / ||），独立检查每个子命令
    sub_commands = split_chain_commands(command)
    if len(sub_commands) > 1:
        return _check_chain_safety(sub_commands)

    return _check_single_command_safety(command)


def get_command_risk_level(command: str) -> RiskLevel:
    """获取命令的风险等级

    通过 PolicyEngine 统一处理白名单 + 规则引擎。
    """
    from src.orchestrator.policy_engine import PolicyEngine

    result = PolicyEngine.check_command(command)
    return result.risk_level if result.risk_level is not None else "medium"
