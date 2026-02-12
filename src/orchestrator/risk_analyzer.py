"""智能命令风险分析引擎 - 四维度分析未知命令的安全风险

当命令未在白名单中匹配时，由此模块接管进行风险评估。
分析管线：类别推断 → 语义分析 → 危险标志检测 → 管道组合分析
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.orchestrator.command_whitelist import CommandCheckResult, parse_command
from src.types import RiskLevel

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class AnalysisTrace:
    """分析过程追踪（用于日志审计）"""

    command: str
    layer1_category: str = "unknown"
    layer1_risk: str = "medium"
    layer2_semantics: list[str] = field(default_factory=list)
    layer2_risk: str = "medium"
    layer3_flags: list[str] = field(default_factory=list)
    layer3_risk: str = "medium"
    layer4_pipe_info: str = ""
    layer4_risk: str = "medium"
    final_risk: str = "medium"

    def summary(self) -> str:
        """生成分析摘要"""
        return (
            f"[RiskAnalyzer] command='{self.command}' "
            f"L1({self.layer1_category}→{self.layer1_risk}) "
            f"L2({','.join(self.layer2_semantics) or 'none'}→{self.layer2_risk}) "
            f"L3({','.join(self.layer3_flags) or 'none'}→{self.layer3_risk}) "
            f"L4({self.layer4_pipe_info or 'none'}→{self.layer4_risk}) "
            f"→ final={self.final_risk}"
        )


# ============================================================
# Layer 1: 命令类别知识库
# ============================================================

COMMAND_CATEGORIES: dict[str, dict[str, object]] = {
    "query": {
        "commands": [
            "cat", "less", "head", "tail", "grep", "find", "which",
            "whereis", "whoami", "hostname", "uname", "df", "du",
            "free", "uptime", "top", "ps", "netstat", "ss", "ip",
            "ifconfig", "ping", "dig", "nslookup", "wc", "file",
            "stat", "lsof", "env", "printenv", "date", "cal",
            "ls", "ll", "pwd", "id", "w", "who", "last",
            "dmesg", "lscpu", "lsmem", "lsblk", "lspci", "lsusb",
            "history", "echo", "printf", "test",
        ],
        "default_risk": "safe",
    },
    "text_processing": {
        "commands": [
            "awk", "sed", "sort", "uniq", "cut", "tr", "diff",
            "comm", "jq", "yq", "base64", "md5sum", "sha256sum",
            "rev", "column", "fmt", "tee",
        ],
        "default_risk": "safe",
    },
    "package_manager": {
        "commands": [
            "npm", "yarn", "pnpm", "pip", "pip3", "gem", "cargo",
            "go", "brew", "apt", "apt-get", "dnf", "yum", "pacman",
            "apk", "composer", "bundler", "npx", "uv",
        ],
        "default_risk": "medium",
    },
    "service_management": {
        "commands": [
            "systemctl", "service", "nginx", "apache2", "httpd",
            "mysql", "mysqld", "redis-cli", "redis-server", "mongod",
            "mongosh", "psql", "pg_ctl", "supervisorctl",
            "pm2", "forever",
        ],
        "default_risk": "medium",
    },
    "container": {
        "commands": [
            "docker", "docker-compose", "podman", "kubectl", "helm",
            "crictl", "nerdctl", "k9s",
        ],
        "default_risk": "medium",
    },
    "version_control": {
        "commands": ["git", "svn", "hg"],
        "default_risk": "safe",
    },
    "language_runtime": {
        "commands": [
            "node", "python", "python3", "ruby", "perl", "php",
            "java", "javac", "rustc", "gcc", "g++", "clang",
            "make", "cmake", "swift", "dotnet", "deno", "bun",
        ],
        "default_risk": "safe",
    },
    "network_tools": {
        "commands": [
            "curl", "wget", "ssh", "scp", "rsync", "sftp", "nc",
            "netcat", "nmap", "traceroute", "tracepath", "mtr",
            "telnet", "host",
        ],
        "default_risk": "medium",
    },
    "monitoring": {
        "commands": [
            "vmstat", "iostat", "sar", "mpstat", "pidstat", "dstat",
            "htop", "iotop", "nethogs", "iftop", "nmon", "perf",
            "strace", "ltrace", "tcpdump",
        ],
        "default_risk": "safe",
    },
    "archive": {
        "commands": [
            "tar", "gzip", "gunzip", "zip", "unzip", "bzip2",
            "xz", "7z",
        ],
        "default_risk": "medium",
    },
    "destructive": {
        "commands": [
            "rm", "rmdir", "kill", "killall", "pkill", "shred",
        ],
        "default_risk": "high",
    },
    "file_write": {
        "commands": [
            "touch", "mkdir", "cp", "mv", "ln", "chmod", "chown",
        ],
        "default_risk": "medium",
    },
}

# 构建命令 → 类别的反向索引
_COMMAND_TO_CATEGORY: dict[str, tuple[str, RiskLevel]] = {}
for _cat_name, _cat_info in COMMAND_CATEGORIES.items():
    _commands = _cat_info["commands"]
    _risk = _cat_info["default_risk"]
    if isinstance(_commands, list) and isinstance(_risk, str):
        for _cmd in _commands:
            _COMMAND_TO_CATEGORY[_cmd] = (_cat_name, _risk)  # type: ignore[assignment]


# ============================================================
# Layer 2: 语义关键词
# ============================================================

SAFE_SEMANTICS: list[str] = [
    "--version", "--help", "-v", "-h", "-V",
    "version", "status", "list", "ls", "show", "info", "get",
    "describe", "inspect", "check", "test", "ping", "health",
    "whoami", "config get", "config list", "config show",
    "top", "log", "logs", "cat", "view", "dump", "export",
    "search", "find", "which", "whereis", "doctor",
    "history", "diff", "blame", "shortlog",
    "ps", "images", "stats", "port", "network", "volume",
    "events", "api-resources", "cluster-info",
    "freeze", "outdated", "config",
    "plan", "validate", "lint", "format", "verify",
]

WRITE_SEMANTICS: list[str] = [
    "install", "add", "create", "mkdir", "touch", "write",
    "set", "update", "upgrade", "build", "init", "config set",
    "apply", "patch", "push", "commit", "enable",
    "pull", "clone", "fetch", "start", "run",
    "exec", "cp", "scale", "rollout",
    "tap", "repo add",
]

DESTRUCTIVE_SEMANTICS: list[str] = [
    "remove", "delete", "rm", "drop", "purge", "uninstall",
    "kill", "stop", "destroy", "reset", "rollback",
    "force-delete", "prune", "clean", "wipe", "truncate",
    "disable", "drain", "cordon", "evict",
    "down", "mask", "unmask",
]


# ============================================================
# Layer 3: 危险标志与路径
# ============================================================

DANGEROUS_FLAGS: dict[str, RiskLevel] = {
    "-rf": "high",
    "-fr": "high",
    "--force": "high",
    "--no-preserve-root": "high",
    "-9": "high",
    "-KILL": "high",
    "--purge": "high",
    "--all": "medium",
    "--recursive": "medium",
    "-R": "medium",
    "--yes": "medium",
    "-y": "medium",
}

DANGEROUS_PATHS: list[str] = [
    "/", "/etc", "/usr", "/var", "/boot", "/sys", "/proc",
    "/bin", "/sbin", "/lib", "/root", "/dev",
]

SAFE_FLAGS: list[str] = [
    "--dry-run", "--check", "--diff", "--simulate",
    "--no-act", "-n", "--whatif", "--preview",
]


# ============================================================
# Layer 4: 管道安全
# ============================================================

SAFE_PIPE_COMMANDS: set[str] = {
    "grep", "egrep", "fgrep", "awk", "sed", "sort", "uniq",
    "wc", "head", "tail", "cut", "tr", "tee", "less", "more",
    "cat", "jq", "yq", "column", "fmt", "rev", "base64",
    "xargs",
}

BLOCKED_PIPE_PATTERNS: list[str] = [
    "| bash", "| sh", "| zsh", "| fish",
    "| sudo", "| su ",
    "| python -c", "| python3 -c", "| perl -e", "| ruby -e",
    "| dd ", "| mkfs",
]


# ============================================================
# 风险等级排序工具
# ============================================================

_RISK_ORDER: dict[str, int] = {
    "safe": 0,
    "medium": 1,
    "high": 2,
    "blocked": 3,
}


def _max_risk(a: str, b: str) -> str:
    """返回较高的风险等级"""
    return a if _RISK_ORDER.get(a, 1) >= _RISK_ORDER.get(b, 1) else b


def _min_risk(a: str, b: str) -> str:
    """返回较低的风险等级"""
    return a if _RISK_ORDER.get(a, 1) <= _RISK_ORDER.get(b, 1) else b


# ============================================================
# 四层分析管线
# ============================================================


def _layer1_category_baseline(base_command: str) -> tuple[str, str]:
    """Layer 1: 根据命令类别推断基线风险

    Returns:
        (类别名, 基线风险等级)
    """
    if base_command in _COMMAND_TO_CATEGORY:
        category, risk = _COMMAND_TO_CATEGORY[base_command]
        return category, risk
    # 完全未知的命令，默认 medium
    return "unknown", "medium"


def _layer2_semantic_analysis(
    base_command: str,
    subcommand: Optional[str],
    args: list[str],
    current_risk: str,
) -> tuple[str, list[str]]:
    """Layer 2: 根据子命令和参数的语义调整风险

    Returns:
        (调整后的风险, 匹配到的语义关键词列表)
    """
    matched_semantics: list[str] = []
    # 合并所有 token 用于匹配
    all_tokens = ([subcommand] if subcommand else []) + args
    token_str = " ".join(all_tokens).lower()

    # 先检查安全语义（可以降低风险）
    for kw in SAFE_SEMANTICS:
        if kw.lower() in token_str or any(t.lower() == kw.lower() for t in all_tokens):
            matched_semantics.append(f"safe:{kw}")
            current_risk = _min_risk(current_risk, "safe")
            # 如果是纯查询型参数（--version, --help），直接返回 safe
            if kw in ("--version", "--help", "-v", "-h", "-V", "version", "help"):
                return "safe", matched_semantics

    # 检查破坏性语义（可以升级风险）
    for kw in DESTRUCTIVE_SEMANTICS:
        if kw.lower() in token_str or any(t.lower() == kw.lower() for t in all_tokens):
            matched_semantics.append(f"destructive:{kw}")
            current_risk = _max_risk(current_risk, "high")

    # 检查写入语义（可以升级风险）
    for kw in WRITE_SEMANTICS:
        if kw.lower() in token_str or any(t.lower() == kw.lower() for t in all_tokens):
            matched_semantics.append(f"write:{kw}")
            current_risk = _max_risk(current_risk, "medium")

    return current_risk, matched_semantics


def _layer3_flag_detection(
    args: list[str],
    current_risk: str,
) -> tuple[str, list[str]]:
    """Layer 3: 检测危险标志和路径

    Returns:
        (调整后的风险, 匹配到的危险标志列表)
    """
    matched_flags: list[str] = []

    # 先检查安全标志（可以降低风险）
    for arg in args:
        if arg in SAFE_FLAGS:
            matched_flags.append(f"safe:{arg}")
            current_risk = _min_risk(current_risk, "safe")

    # 检查危险标志
    for arg in args:
        for flag, flag_risk in DANGEROUS_FLAGS.items():
            if arg == flag or arg.startswith(f"{flag}="):
                matched_flags.append(f"danger:{flag}")
                current_risk = _max_risk(current_risk, flag_risk)
            # 检查合并的短参数，如 -rf
            elif (
                arg.startswith("-")
                and not arg.startswith("--")
                and len(flag) == 2
                and flag.startswith("-")
            ):
                flag_char = flag[1]
                if flag_char in arg[1:]:
                    matched_flags.append(f"danger:{flag}(in {arg})")
                    current_risk = _max_risk(current_risk, flag_risk)

    # 检查危险路径
    for arg in args:
        for dangerous_path in DANGEROUS_PATHS:
            # 精确匹配根路径 "/" 或者参数以危险路径开头
            if arg == dangerous_path or (
                dangerous_path != "/" and arg.startswith(dangerous_path + "/")
            ):
                matched_flags.append(f"path:{dangerous_path}")
                current_risk = _max_risk(current_risk, "high")
                break
        # 精确匹配 "/"
        if arg == "/":
            if "path:/" not in matched_flags:
                matched_flags.append("path:/")
            current_risk = "blocked"

    return current_risk, matched_flags


def _layer4_pipe_analysis(command: str, current_risk: str) -> tuple[str, str]:
    """Layer 4: 管道与组合命令分析

    Returns:
        (调整后的风险, 管道分析信息)
    """
    # 检查绝对禁止的管道模式
    command_lower = command.lower()
    for pattern in BLOCKED_PIPE_PATTERNS:
        if pattern.lower() in command_lower:
            return "blocked", f"blocked_pattern:{pattern}"

    # 检查是否有管道
    if "|" not in command:
        return current_risk, "no_pipe"

    # 拆分管道，分析每段
    pipe_parts = command.split("|")
    pipe_info_parts: list[str] = []

    for part in pipe_parts[1:]:
        part = part.strip()
        if not part:
            continue
        pipe_cmd, _, _ = parse_command(part)
        if pipe_cmd in SAFE_PIPE_COMMANDS:
            pipe_info_parts.append(f"{pipe_cmd}(safe)")
        else:
            # 管道中出现非安全命令，升级风险
            pipe_info_parts.append(f"{pipe_cmd}(unknown)")
            current_risk = _max_risk(current_risk, "medium")

    pipe_info = "pipe:" + ",".join(pipe_info_parts) if pipe_info_parts else "pipe:empty"
    return current_risk, pipe_info


# ============================================================
# 主入口
# ============================================================


def analyze_command_risk(command: str) -> CommandCheckResult:
    """四维度分析未知命令的风险等级

    当命令未在白名单中匹配时调用此函数进行智能风险分析。

    Args:
        command: 待分析的 shell 命令字符串

    Returns:
        CommandCheckResult，包含 allowed, risk_level, reason, matched_by
    """
    trace = AnalysisTrace(command=command)

    # 解析命令
    base_command, subcommand, args = parse_command(command)

    # Layer 1: 类别推断
    category, risk = _layer1_category_baseline(base_command)
    trace.layer1_category = category
    trace.layer1_risk = risk

    # Layer 2: 语义分析
    risk, semantics = _layer2_semantic_analysis(base_command, subcommand, args, risk)
    trace.layer2_semantics = semantics
    trace.layer2_risk = risk

    # Layer 3: 危险标志检测
    risk, flags = _layer3_flag_detection(args, risk)
    trace.layer3_flags = flags
    trace.layer3_risk = risk

    # Layer 4: 管道组合分析
    risk, pipe_info = _layer4_pipe_analysis(command, risk)
    trace.layer4_pipe_info = pipe_info
    trace.layer4_risk = risk

    trace.final_risk = risk

    # 记录分析日志
    logger.info(trace.summary())

    # 构造结果
    if risk == "blocked":
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=f"Risk analyzer blocked: {trace.summary()}",
            matched_by="risk_analyzer",
        )

    # 确保 risk_level 是合法的 RiskLevel
    valid_risk: RiskLevel = risk if risk in ("safe", "medium", "high") else "medium"

    return CommandCheckResult(
        allowed=True,
        risk_level=valid_risk,
        reason=f"Risk analyzer approved ({valid_risk}): {category}",
        matched_by="risk_analyzer",
    )
