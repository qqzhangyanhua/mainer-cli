"""Shell 命令白名单模块 - 精确的命令级权限控制"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional

from src.types import RiskLevel


@dataclass
class CommandRule:
    """命令规则定义"""

    base_command: str  # 基础命令，如 "docker"
    subcommand: Optional[str] = None  # 子命令，如 "ps"（None 表示匹配所有子命令）
    risk_level: RiskLevel = "safe"  # 风险等级
    blocked_flags: Optional[list[str]] = None  # 禁止的参数，如 ["-rf", "--force"]
    description: str = ""  # 规则描述


# 命令白名单定义
# 规则优先级：更具体的规则优先（有 subcommand > 无 subcommand）
COMMAND_WHITELIST: list[CommandRule] = [
    # ========== 文件系统（只读）==========
    CommandRule("ls", risk_level="safe", description="列出目录内容"),
    CommandRule("ll", risk_level="safe", description="列出目录详情"),
    CommandRule("cat", risk_level="safe", description="查看文件内容"),
    CommandRule("head", risk_level="safe", description="查看文件头部"),
    CommandRule("tail", risk_level="safe", description="查看文件尾部"),
    CommandRule("less", risk_level="safe", description="分页查看文件"),
    CommandRule("more", risk_level="safe", description="分页查看文件"),
    CommandRule("wc", risk_level="safe", description="统计行数/字数"),
    CommandRule("file", risk_level="safe", description="查看文件类型"),
    CommandRule("stat", risk_level="safe", description="查看文件状态"),
    CommandRule("find", risk_level="safe", blocked_flags=["-delete", "-exec"], description="查找文件"),
    CommandRule("locate", risk_level="safe", description="快速定位文件"),
    CommandRule("which", risk_level="safe", description="查找命令路径"),
    CommandRule("whereis", risk_level="safe", description="查找命令位置"),
    CommandRule("readlink", risk_level="safe", description="读取符号链接"),
    CommandRule("realpath", risk_level="safe", description="获取真实路径"),
    # ========== 文本处理（只读）==========
    CommandRule("grep", risk_level="safe", description="文本搜索"),
    CommandRule("egrep", risk_level="safe", description="扩展正则搜索"),
    CommandRule("fgrep", risk_level="safe", description="固定字符串搜索"),
    CommandRule("awk", risk_level="safe", description="文本处理"),
    CommandRule("sed", risk_level="safe", blocked_flags=["-i"], description="流编辑器（禁止原地修改）"),
    CommandRule("sort", risk_level="safe", description="排序"),
    CommandRule("uniq", risk_level="safe", description="去重"),
    CommandRule("cut", risk_level="safe", description="列切割"),
    CommandRule("tr", risk_level="safe", description="字符转换"),
    CommandRule("diff", risk_level="safe", description="文件比较"),
    CommandRule("comm", risk_level="safe", description="文件比较"),
    CommandRule("tee", risk_level="medium", description="同时输出到文件和标准输出"),
    # ========== 系统信息（只读）==========
    CommandRule("df", risk_level="safe", description="磁盘使用情况"),
    CommandRule("du", risk_level="safe", description="目录大小"),
    CommandRule("free", risk_level="safe", description="内存使用情况"),
    CommandRule("top", risk_level="safe", description="进程监控"),
    CommandRule("htop", risk_level="safe", description="交互式进程监控"),
    CommandRule("ps", risk_level="safe", description="进程列表"),
    CommandRule("pgrep", risk_level="safe", description="进程搜索"),
    CommandRule("lsof", risk_level="safe", description="打开文件列表"),
    CommandRule("netstat", risk_level="safe", description="网络状态"),
    CommandRule("ss", risk_level="safe", description="套接字状态"),
    CommandRule("ip", risk_level="safe", description="网络配置查看"),
    CommandRule("ifconfig", risk_level="safe", description="网络接口配置"),
    CommandRule("hostname", risk_level="safe", description="主机名"),
    CommandRule("uname", risk_level="safe", description="系统信息"),
    CommandRule("uptime", risk_level="safe", description="运行时间"),
    CommandRule("whoami", risk_level="safe", description="当前用户"),
    CommandRule("id", risk_level="safe", description="用户ID信息"),
    CommandRule("w", risk_level="safe", description="登录用户"),
    CommandRule("who", risk_level="safe", description="登录用户"),
    CommandRule("last", risk_level="safe", description="登录历史"),
    CommandRule("date", risk_level="safe", description="日期时间"),
    CommandRule("cal", risk_level="safe", description="日历"),
    CommandRule("env", risk_level="safe", description="环境变量"),
    CommandRule("printenv", risk_level="safe", description="打印环境变量"),
    CommandRule("echo", risk_level="safe", description="输出文本"),
    CommandRule("printf", risk_level="safe", description="格式化输出"),
    CommandRule("pwd", risk_level="safe", description="当前目录"),
    CommandRule("history", risk_level="safe", description="命令历史"),
    CommandRule("dmesg", risk_level="safe", description="内核消息"),
    CommandRule("lscpu", risk_level="safe", description="CPU信息"),
    CommandRule("lsmem", risk_level="safe", description="内存信息"),
    CommandRule("lsblk", risk_level="safe", description="块设备信息"),
    CommandRule("lspci", risk_level="safe", description="PCI设备"),
    CommandRule("lsusb", risk_level="safe", description="USB设备"),
    # ========== 网络工具（只读）==========
    CommandRule("ping", risk_level="safe", description="网络连通性测试"),
    CommandRule("curl", risk_level="safe", description="HTTP 请求"),
    CommandRule("wget", risk_level="medium", description="下载文件"),
    CommandRule("dig", risk_level="safe", description="DNS 查询"),
    CommandRule("nslookup", risk_level="safe", description="DNS 查询"),
    CommandRule("host", risk_level="safe", description="DNS 查询"),
    CommandRule("traceroute", risk_level="safe", description="路由追踪"),
    CommandRule("tracepath", risk_level="safe", description="路由追踪"),
    CommandRule("nc", risk_level="medium", description="网络连接工具"),
    CommandRule("netcat", risk_level="medium", description="网络连接工具"),
    CommandRule("telnet", risk_level="medium", description="远程连接"),
    # ========== Docker 命令 ==========
    CommandRule("docker", "ps", risk_level="safe", description="列出容器"),
    CommandRule("docker", "images", risk_level="safe", description="列出镜像"),
    CommandRule("docker", "logs", risk_level="safe", description="查看日志"),
    CommandRule("docker", "inspect", risk_level="safe", description="查看详情"),
    CommandRule("docker", "stats", risk_level="safe", description="资源统计"),
    CommandRule("docker", "top", risk_level="safe", description="容器进程"),
    CommandRule("docker", "port", risk_level="safe", description="端口映射"),
    CommandRule("docker", "diff", risk_level="safe", description="文件变更"),
    CommandRule("docker", "history", risk_level="safe", description="镜像历史"),
    CommandRule("docker", "version", risk_level="safe", description="版本信息"),
    CommandRule("docker", "info", risk_level="safe", description="系统信息"),
    CommandRule("docker", "network", risk_level="safe", description="网络信息"),
    CommandRule("docker", "volume", risk_level="safe", description="卷信息"),
    CommandRule("docker", "exec", risk_level="medium", description="容器内执行命令"),
    CommandRule("docker", "cp", risk_level="medium", description="容器文件复制"),
    CommandRule("docker", "start", risk_level="medium", description="启动容器"),
    CommandRule("docker", "stop", risk_level="medium", description="停止容器"),
    CommandRule("docker", "restart", risk_level="medium", description="重启容器"),
    CommandRule("docker", "pause", risk_level="medium", description="暂停容器"),
    CommandRule("docker", "unpause", risk_level="medium", description="恢复容器"),
    CommandRule("docker", "pull", risk_level="medium", description="拉取镜像"),
    CommandRule("docker", "build", risk_level="medium", description="构建镜像"),
    CommandRule("docker", "run", risk_level="high", description="运行容器"),
    CommandRule("docker", "rm", risk_level="high", description="删除容器"),
    CommandRule("docker", "rmi", risk_level="high", description="删除镜像"),
    CommandRule("docker", "kill", risk_level="high", description="强制停止容器"),
    CommandRule("docker", "prune", risk_level="high", description="清理资源"),
    # ========== Docker Compose ==========
    CommandRule("docker-compose", "ps", risk_level="safe", description="列出服务"),
    CommandRule("docker-compose", "logs", risk_level="safe", description="查看日志"),
    CommandRule("docker-compose", "config", risk_level="safe", description="验证配置"),
    CommandRule("docker-compose", "images", risk_level="safe", description="列出镜像"),
    CommandRule("docker-compose", "top", risk_level="safe", description="服务进程"),
    CommandRule("docker-compose", "start", risk_level="medium", description="启动服务"),
    CommandRule("docker-compose", "stop", risk_level="medium", description="停止服务"),
    CommandRule("docker-compose", "restart", risk_level="medium", description="重启服务"),
    CommandRule("docker-compose", "up", risk_level="medium", description="启动所有服务"),
    CommandRule("docker-compose", "pull", risk_level="medium", description="拉取镜像"),
    CommandRule("docker-compose", "build", risk_level="medium", description="构建服务"),
    CommandRule("docker-compose", "down", risk_level="high", description="停止并删除"),
    CommandRule("docker-compose", "rm", risk_level="high", description="删除容器"),
    # ========== Git 命令 ==========
    CommandRule("git", "status", risk_level="safe", description="仓库状态"),
    CommandRule("git", "log", risk_level="safe", description="提交历史"),
    CommandRule("git", "diff", risk_level="safe", description="差异比较"),
    CommandRule("git", "show", risk_level="safe", description="显示对象"),
    CommandRule("git", "branch", risk_level="safe", description="分支列表"),
    CommandRule("git", "remote", risk_level="safe", description="远程仓库"),
    CommandRule("git", "tag", risk_level="safe", description="标签列表"),
    CommandRule("git", "config", risk_level="safe", description="配置信息"),
    CommandRule("git", "ls-files", risk_level="safe", description="跟踪文件"),
    CommandRule("git", "ls-tree", risk_level="safe", description="树对象"),
    CommandRule("git", "blame", risk_level="safe", description="行追溯"),
    CommandRule("git", "shortlog", risk_level="safe", description="简短日志"),
    CommandRule("git", "describe", risk_level="safe", description="描述标签"),
    CommandRule("git", "rev-parse", risk_level="safe", description="解析引用"),
    CommandRule("git", "fetch", risk_level="medium", description="获取远程"),
    CommandRule("git", "pull", risk_level="medium", description="拉取更新"),
    CommandRule("git", "clone", risk_level="medium", description="克隆仓库"),
    CommandRule("git", "checkout", risk_level="medium", description="切换分支"),
    CommandRule("git", "switch", risk_level="medium", description="切换分支"),
    CommandRule("git", "add", risk_level="medium", description="暂存文件"),
    CommandRule("git", "commit", risk_level="medium", description="提交更改"),
    CommandRule("git", "stash", risk_level="medium", description="暂存更改"),
    CommandRule("git", "merge", risk_level="medium", description="合并分支"),
    CommandRule("git", "rebase", risk_level="medium", description="变基"),
    CommandRule("git", "push", risk_level="high", description="推送到远程"),
    CommandRule(
        "git", "reset", risk_level="high", blocked_flags=["--hard"], description="重置（禁止 --hard）"
    ),
    CommandRule("git", "clean", risk_level="high", description="清理未跟踪文件"),
    # ========== Systemd 服务管理 ==========
    CommandRule("systemctl", "status", risk_level="safe", description="服务状态"),
    CommandRule("systemctl", "is-active", risk_level="safe", description="是否活跃"),
    CommandRule("systemctl", "is-enabled", risk_level="safe", description="是否启用"),
    CommandRule("systemctl", "list-units", risk_level="safe", description="单元列表"),
    CommandRule("systemctl", "list-unit-files", risk_level="safe", description="单元文件列表"),
    CommandRule("systemctl", "show", risk_level="safe", description="显示属性"),
    CommandRule("systemctl", "cat", risk_level="safe", description="显示配置"),
    CommandRule("journalctl", risk_level="safe", description="查看日志"),
    CommandRule("systemctl", "start", risk_level="medium", description="启动服务"),
    CommandRule("systemctl", "stop", risk_level="medium", description="停止服务"),
    CommandRule("systemctl", "restart", risk_level="medium", description="重启服务"),
    CommandRule("systemctl", "reload", risk_level="medium", description="重载配置"),
    CommandRule("systemctl", "enable", risk_level="high", description="启用服务"),
    CommandRule("systemctl", "disable", risk_level="high", description="禁用服务"),
    CommandRule("systemctl", "mask", risk_level="high", description="屏蔽服务"),
    CommandRule("systemctl", "unmask", risk_level="high", description="取消屏蔽"),
    # ========== 包管理（只读）==========
    CommandRule("apt", "list", risk_level="safe", description="列出包"),
    CommandRule("apt", "show", risk_level="safe", description="包详情"),
    CommandRule("apt", "search", risk_level="safe", description="搜索包"),
    CommandRule("apt-cache", risk_level="safe", description="包缓存查询"),
    CommandRule("dpkg", "-l", risk_level="safe", description="列出已安装包"),
    CommandRule("dpkg", "-L", risk_level="safe", description="包文件列表"),
    CommandRule("dpkg", "-s", risk_level="safe", description="包状态"),
    CommandRule("yum", "list", risk_level="safe", description="列出包"),
    CommandRule("yum", "info", risk_level="safe", description="包信息"),
    CommandRule("yum", "search", risk_level="safe", description="搜索包"),
    CommandRule("rpm", "-qa", risk_level="safe", description="列出已安装包"),
    CommandRule("rpm", "-qi", risk_level="safe", description="包信息"),
    CommandRule("rpm", "-ql", risk_level="safe", description="包文件列表"),
    CommandRule("pip", "list", risk_level="safe", description="Python 包列表"),
    CommandRule("pip", "show", risk_level="safe", description="Python 包详情"),
    CommandRule("pip", "freeze", risk_level="safe", description="Python 依赖"),
    CommandRule("npm", "list", risk_level="safe", description="Node 包列表"),
    CommandRule("npm", "view", risk_level="safe", description="包详情"),
    CommandRule("npm", "outdated", risk_level="safe", description="过期包"),
    # ========== 文件操作（写入）==========
    CommandRule("touch", risk_level="medium", description="创建空文件"),
    CommandRule("mkdir", risk_level="medium", description="创建目录"),
    CommandRule("cp", risk_level="medium", description="复制文件"),
    CommandRule("mv", risk_level="medium", description="移动文件"),
    CommandRule("ln", risk_level="medium", description="创建链接"),
    CommandRule("rm", risk_level="high", blocked_flags=["-rf", "-fr", "--recursive"], description="删除文件"),
    CommandRule("rmdir", risk_level="medium", description="删除空目录"),
    CommandRule("chmod", risk_level="high", blocked_flags=["-R", "777"], description="修改权限"),
    CommandRule("chown", risk_level="high", blocked_flags=["-R"], description="修改所有者"),
    # ========== 进程管理 ==========
    CommandRule("kill", risk_level="high", blocked_flags=["-9", "-KILL"], description="终止进程"),
    CommandRule("pkill", risk_level="high", description="按名称终止进程"),
    CommandRule("killall", risk_level="high", description="终止所有匹配进程"),
    # ========== 其他常用工具 ==========
    CommandRule("jq", risk_level="safe", description="JSON 处理"),
    CommandRule("yq", risk_level="safe", description="YAML 处理"),
    CommandRule("xargs", risk_level="medium", description="参数传递"),
    CommandRule("tar", risk_level="medium", description="归档工具"),
    CommandRule("gzip", risk_level="medium", description="压缩"),
    CommandRule("gunzip", risk_level="medium", description="解压"),
    CommandRule("zip", risk_level="medium", description="ZIP 压缩"),
    CommandRule("unzip", risk_level="medium", description="ZIP 解压"),
    CommandRule("base64", risk_level="safe", description="Base64 编解码"),
    CommandRule("md5sum", risk_level="safe", description="MD5 校验"),
    CommandRule("sha256sum", risk_level="safe", description="SHA256 校验"),
    CommandRule("openssl", risk_level="safe", description="SSL 工具"),
    CommandRule("ssh-keygen", risk_level="medium", description="SSH 密钥生成"),
    CommandRule("crontab", "-l", risk_level="safe", description="查看定时任务"),
    CommandRule("crontab", "-e", risk_level="high", description="编辑定时任务"),
]

# 绝对禁止的命令（无论如何都不允许）
BLOCKED_COMMANDS: set[str] = {
    "dd",  # 磁盘操作
    "mkfs",  # 格式化
    "fdisk",  # 分区
    "parted",  # 分区
    "mount",  # 挂载
    "umount",  # 卸载
    "sudo",  # 提权
    "su",  # 切换用户
    "passwd",  # 修改密码
    "useradd",  # 添加用户
    "userdel",  # 删除用户
    "groupadd",  # 添加组
    "groupdel",  # 删除组
    "visudo",  # 编辑 sudoers
    "shutdown",  # 关机
    "reboot",  # 重启
    "init",  # 系统初始化
    "poweroff",  # 关机
    "halt",  # 停机
    "iptables",  # 防火墙
    "firewall-cmd",  # 防火墙
    "ufw",  # 防火墙
    "nft",  # nftables
    "eval",  # 执行字符串
    "exec",  # 替换进程
    "source",  # 执行脚本
    ".",  # source 别名
}

# 危险的 shell 元字符和模式
DANGEROUS_PATTERNS: list[str] = [
    "$(", "`",  # 命令替换
    "&&", "||", ";",  # 命令链接（单命令白名单不允许链接）
    "|",  # 管道（单独处理）
    ">", ">>", "<",  # 重定向
    "&",  # 后台执行
    "\\n", "\\r",  # 换行注入
    "${",  # 变量展开
    "~",  # 主目录展开（某些场景危险）
]

# 允许的管道命令（只读的文本处理工具）
ALLOWED_PIPE_COMMANDS: set[str] = {
    "grep", "egrep", "fgrep",
    "awk", "sed",
    "sort", "uniq", "cut", "tr",
    "head", "tail", "wc",
    "jq", "yq",
    "less", "more",
    "cat", "tee",
    "xargs",
    "base64",
}


@dataclass
class CommandCheckResult:
    """命令检查结果"""

    allowed: bool  # 是否允许执行
    risk_level: RiskLevel  # 风险等级
    reason: str  # 允许/拒绝原因
    matched_rule: Optional[CommandRule] = None  # 匹配的规则


def parse_command(command: str) -> tuple[str, Optional[str], list[str]]:
    """解析命令，提取基础命令、子命令和参数

    Args:
        command: 完整命令字符串

    Returns:
        (base_command, subcommand, args)
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # 解析失败，返回原始命令
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
        # 对于 docker/git/systemctl 等，第二个非 - 开头的 token 是子命令
        if base_command in {"docker", "docker-compose", "git", "systemctl", "apt", "yum", "npm", "pip"}:
            for i, token in enumerate(tokens[1:], 1):
                if not token.startswith("-"):
                    subcommand = token
                    args = tokens[i + 1 :]
                    break
            else:
                args = tokens[1:]
        else:
            args = tokens[1:]

    return base_command, subcommand, args


def check_dangerous_patterns(command: str) -> Optional[str]:
    """检查危险模式

    Args:
        command: 命令字符串

    Returns:
        如果发现危险模式返回原因，否则返回 None
    """
    # 检查命令链接和重定向
    for pattern in DANGEROUS_PATTERNS:
        if pattern in command:
            # 允许管道，但需要额外检查
            if pattern == "|":
                continue
            return f"Dangerous pattern detected: '{pattern}'"

    return None


def check_pipe_safety(command: str) -> Optional[str]:
    """检查管道命令安全性

    Args:
        command: 包含管道的命令

    Returns:
        如果不安全返回原因，否则返回 None
    """
    if "|" not in command:
        return None

    # 分割管道命令
    pipe_parts = command.split("|")

    for part in pipe_parts[1:]:  # 跳过第一个命令（由主检查处理）
        part = part.strip()
        if not part:
            continue

        base_cmd, _, _ = parse_command(part)

        if base_cmd not in ALLOWED_PIPE_COMMANDS:
            return f"Command '{base_cmd}' is not allowed in pipe. Allowed: {', '.join(sorted(ALLOWED_PIPE_COMMANDS))}"

    return None


def find_matching_rule(
    base_command: str, subcommand: Optional[str]
) -> Optional[CommandRule]:
    """查找匹配的规则

    Args:
        base_command: 基础命令
        subcommand: 子命令

    Returns:
        匹配的规则，如果没有匹配返回 None
    """
    # 优先查找精确匹配（有 subcommand）
    for rule in COMMAND_WHITELIST:
        if rule.base_command == base_command and rule.subcommand == subcommand:
            return rule

    # 其次查找通用规则（无 subcommand）
    for rule in COMMAND_WHITELIST:
        if rule.base_command == base_command and rule.subcommand is None:
            return rule

    return None


def check_blocked_flags(rule: CommandRule, args: list[str]) -> Optional[str]:
    """检查是否包含禁止的参数

    Args:
        rule: 命令规则
        args: 命令参数列表

    Returns:
        如果包含禁止参数返回原因，否则返回 None
    """
    if not rule.blocked_flags:
        return None

    for arg in args:
        for blocked in rule.blocked_flags:
            # 精确匹配或前缀匹配
            if arg == blocked or arg.startswith(f"{blocked}="):
                return f"Flag '{blocked}' is not allowed for command '{rule.base_command}'"

            # 检查组合参数，如 -rf
            if arg.startswith("-") and not arg.startswith("--"):
                # 短参数，检查每个字符
                for char in arg[1:]:
                    if f"-{char}" in rule.blocked_flags or char in rule.blocked_flags:
                        return f"Flag '-{char}' is not allowed for command '{rule.base_command}'"

    return None


def check_command_safety(command: str) -> CommandCheckResult:
    """检查命令是否安全

    Args:
        command: 要检查的命令

    Returns:
        CommandCheckResult 包含检查结果
    """
    command = command.strip()

    if not command:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason="Empty command",
        )

    # 1. 检查危险模式（除管道外）
    danger_reason = check_dangerous_patterns(command)
    if danger_reason:
        return CommandCheckResult(
            allowed=False,
            risk_level="high",
            reason=danger_reason,
        )

    # 2. 解析命令
    base_command, subcommand, args = parse_command(command)

    # 3. 检查是否在绝对禁止列表
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
            reason=f"Command '{base_command}' is not in whitelist. Use dedicated Workers for specific tasks.",
        )

    # 5. 检查禁止的参数
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

    # 7. 通过检查
    return CommandCheckResult(
        allowed=True,
        risk_level=rule.risk_level,
        reason=f"Allowed: {rule.description}",
        matched_rule=rule,
    )


def get_command_risk_level(command: str) -> RiskLevel:
    """获取命令的风险等级（供 safety.py 调用）

    Args:
        command: 命令字符串

    Returns:
        RiskLevel
    """
    result = check_command_safety(command)
    return result.risk_level
