"""Shell 命令白名单规则定义 - 纯数据"""

from __future__ import annotations

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
    CommandRule("test", risk_level="safe", description="测试路径/条件"),
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
    "dd", "mkfs", "fdisk", "parted", "mount", "umount",
    "sudo", "su", "passwd", "useradd", "userdel", "groupadd", "groupdel", "visudo",
    "shutdown", "reboot", "init", "poweroff", "halt",
    "iptables", "firewall-cmd", "ufw", "nft",
    "eval", "exec", "source", ".",
}

# 危险的 shell 元字符和模式
DANGEROUS_PATTERNS: list[str] = [
    "$(", "`",  # 命令替换
    "&&", "||", ";",  # 命令链接
    "|",  # 管道（单独处理）
    ">", ">>", "<",  # 重定向
    "&",  # 后台执行
    "\\n", "\\r",  # 换行注入
    "${",  # 变量展开
    "~",  # 主目录展开
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
