"""环境检测器模块

用于首次运行时检测当前环境，生成个性化的欢迎信息和操作建议。
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import List


@dataclass
class EnvironmentInfo:
    """环境信息

    包含当前运行环境的详细信息，用于生成个性化建议。
    """

    has_docker: bool
    docker_containers: int
    has_systemd: bool
    systemd_services: List[str]
    has_kubernetes: bool
    disk_usage: float  # 百分比
    memory_usage: float  # 百分比
    os_type: str
    os_version: str


class EnvironmentDetector:
    """环境检测器

    检测当前系统环境，包括：
    - Docker 运行状态和容器数量
    - Systemd 服务状态
    - Kubernetes 可用性
    - 磁盘和内存使用率
    """

    # 常见的重要 systemd 服务
    IMPORTANT_SERVICES: List[str] = [
        "nginx",
        "apache2",
        "httpd",
        "mysql",
        "mysqld",
        "postgresql",
        "redis",
        "redis-server",
        "mongodb",
        "mongod",
        "docker",
        "containerd",
        "ssh",
        "sshd",
    ]

    def detect(self) -> EnvironmentInfo:
        """检测当前环境

        Returns:
            包含环境信息的 EnvironmentInfo 对象
        """
        return EnvironmentInfo(
            has_docker=self._check_docker(),
            docker_containers=self._count_containers(),
            has_systemd=self._check_systemd(),
            systemd_services=self._list_important_services(),
            has_kubernetes=self._check_kubernetes(),
            disk_usage=self._get_disk_usage(),
            memory_usage=self._get_memory_usage(),
            os_type=platform.system(),
            os_version=platform.release(),
        )

    def _check_docker(self) -> bool:
        """检查 Docker 是否运行

        Returns:
            Docker 是否可用并运行
        """
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _count_containers(self) -> int:
        """统计运行中的容器数量

        Returns:
            运行中的 Docker 容器数量
        """
        try:
            result = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode != 0:
                return 0
            output = result.stdout.strip()
            if not output:
                return 0
            return len(output.split("\n"))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return 0

    def _check_systemd(self) -> bool:
        """检查 Systemd 是否可用

        Returns:
            Systemd 是否可用
        """
        try:
            result = subprocess.run(
                ["systemctl", "--version"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _list_important_services(self) -> List[str]:
        """列出正在运行的重要 systemd 服务

        Returns:
            正在运行的重要服务列表
        """
        if not self._check_systemd():
            return []

        running: List[str] = []
        for service in self.IMPORTANT_SERVICES:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                )
                if result.stdout.strip() == "active":
                    running.append(service)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

        return running

    def _check_kubernetes(self) -> bool:
        """检查 Kubernetes (kubectl) 是否可用

        Returns:
            kubectl 是否可用
        """
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _get_disk_usage(self) -> float:
        """获取根目录磁盘使用率

        Returns:
            磁盘使用率百分比（0-100）
        """
        os_type = platform.system()

        try:
            if os_type == "Darwin":
                # macOS 使用 df 命令
                result = subprocess.run(
                    ["df", "-h", "/"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    # macOS df 输出格式: Filesystem Size Used Avail Capacity iused ifree %iused Mounted
                    parts = lines[1].split()
                    for part in parts:
                        if part.endswith("%") and not part.startswith("i"):
                            return float(part.rstrip("%"))
            else:
                # Linux 使用 df 命令
                result = subprocess.run(
                    ["df", "-h", "/"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    parts = lines[1].split()
                    if len(parts) >= 5:
                        usage_str = parts[4].rstrip("%")
                        return float(usage_str)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass

        return 0.0

    def _get_memory_usage(self) -> float:
        """获取内存使用率

        Returns:
            内存使用率百分比（0-100）
        """
        os_type = platform.system()

        try:
            if os_type == "Darwin":
                # macOS 使用 vm_stat
                result = subprocess.run(
                    ["vm_stat"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                lines = result.stdout.strip().split("\n")

                page_size = 4096  # 默认页面大小
                free_pages = 0
                active_pages = 0
                inactive_pages = 0
                wired_pages = 0

                for line in lines:
                    if "page size of" in line:
                        # 解析页面大小
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if p == "of" and i + 1 < len(parts):
                                page_size = int(parts[i + 1])
                                break
                    elif "Pages free:" in line:
                        free_pages = int(line.split(":")[1].strip().rstrip("."))
                    elif "Pages active:" in line:
                        active_pages = int(line.split(":")[1].strip().rstrip("."))
                    elif "Pages inactive:" in line:
                        inactive_pages = int(line.split(":")[1].strip().rstrip("."))
                    elif "Pages wired down:" in line:
                        wired_pages = int(line.split(":")[1].strip().rstrip("."))

                total = free_pages + active_pages + inactive_pages + wired_pages
                if total > 0:
                    used = active_pages + wired_pages
                    return (used / total) * 100
            else:
                # Linux 使用 free 命令
                result = subprocess.run(
                    ["free", "-m"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    parts = lines[1].split()
                    if len(parts) >= 3:
                        total = float(parts[1])
                        used = float(parts[2])
                        if total > 0:
                            return (used / total) * 100
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass

        return 0.0

    def generate_suggestions(self, env_info: EnvironmentInfo) -> List[str]:
        """根据环境生成操作建议

        Args:
            env_info: 环境信息

        Returns:
            推荐操作列表（固定 3 个）
        """
        suggestions: List[str] = []

        # 优先级 1: Docker 相关
        if env_info.has_docker and env_info.docker_containers > 0:
            suggestions.append("查看所有容器状态")

        # 优先级 2: 磁盘警告
        if env_info.disk_usage > 70:
            suggestions.append("查看磁盘使用情况")

        # 优先级 3: 服务日志
        if env_info.systemd_services:
            suggestions.append(f"查看 {env_info.systemd_services[0]} 服务日志")
        elif env_info.has_docker and env_info.docker_containers > 0:
            suggestions.append("查看容器日志")
        else:
            suggestions.append("查看系统日志")

        # 优先级 4: Kubernetes
        if env_info.has_kubernetes and len(suggestions) < 3:
            suggestions.append("查看 Kubernetes 集群状态")

        # 保底建议（确保有 3 个）
        fallback_suggestions = [
            "检查系统资源占用",
            "查看当前目录文件",
            "部署 GitHub 项目",
        ]
        for fallback in fallback_suggestions:
            if len(suggestions) >= 3:
                break
            if fallback not in suggestions:
                suggestions.append(fallback)

        return suggestions[:3]

    def generate_welcome_message(self, env_info: EnvironmentInfo) -> str:
        """生成欢迎消息

        Args:
            env_info: 环境信息

        Returns:
            格式化的欢迎消息
        """
        parts: List[str] = [
            "欢迎使用 OpsAI！",
            "",
            "我已经检测到你的环境：",
        ]

        # 操作系统信息
        parts.append(f"  系统: {env_info.os_type} {env_info.os_version}")

        # Docker 信息
        if env_info.has_docker:
            container_text = f"({env_info.docker_containers} 个运行中)"
            parts.append(f"  Docker 正在运行 {container_text}")
        else:
            parts.append("  Docker 未运行")

        # Systemd 信息
        if env_info.has_systemd:
            if env_info.systemd_services:
                services_str = ", ".join(env_info.systemd_services[:3])
                if len(env_info.systemd_services) > 3:
                    services_str += "..."
                parts.append(f"  Systemd 服务: {services_str}")
            else:
                parts.append("  Systemd 服务管理器")

        # Kubernetes 信息
        if env_info.has_kubernetes:
            parts.append("  Kubernetes (kubectl) 可用")

        # 资源警告
        parts.append("")
        if env_info.disk_usage > 80:
            parts.append(f"  磁盘使用率 {env_info.disk_usage:.0f}%（建议清理）")
        elif env_info.disk_usage > 0:
            parts.append(f"  磁盘使用率 {env_info.disk_usage:.0f}%")

        if env_info.memory_usage > 80:
            parts.append(f"  内存使用率 {env_info.memory_usage:.0f}%（较高）")
        elif env_info.memory_usage > 0:
            parts.append(f"  内存使用率 {env_info.memory_usage:.0f}%")

        # 推荐操作
        suggestions = self.generate_suggestions(env_info)
        parts.extend(
            [
                "",
                "推荐你试试这些操作：",
            ]
        )
        for i, suggestion in enumerate(suggestions, 1):
            parts.append(f"  {i}. {suggestion}")

        parts.extend(
            [
                "",
                "提示：直接用自然语言描述你的需求即可",
                '例如："查看日志"、"重启服务"、"磁盘快满了"',
            ]
        )

        return "\n".join(parts)
