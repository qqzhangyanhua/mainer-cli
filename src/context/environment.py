"""环境信息收集模块"""

import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EnvironmentContext:
    """环境上下文信息

    在启动时收集一次，会话期间不再更新
    """

    os_type: str = field(init=False)
    os_version: str = field(init=False)
    shell: str = field(init=False)
    cwd: str = field(init=False)
    user: str = field(init=False)
    docker_available: bool = field(init=False)
    timestamp: str = field(init=False)

    def __post_init__(self) -> None:
        """初始化并收集环境信息"""
        self.os_type = platform.system()
        self.os_version = platform.release()
        self.shell = os.environ.get("SHELL", "unknown")
        self.cwd = os.getcwd()
        self.user = os.environ.get("USER", "unknown")
        self.docker_available = self._check_docker()
        self.timestamp = datetime.now().isoformat()

    def _check_docker(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def to_prompt_context(self) -> str:
        """转换为 LLM Prompt 的上下文字符串

        Returns:
            格式化的环境信息字符串
        """
        docker_status = "Available" if self.docker_available else "Not available"
        return f"""Current Environment:
- OS: {self.os_type} {self.os_version}
- Shell: {self.shell}
- Working Directory: {self.cwd}
- Docker: {docker_status}
- User: {self.user}
"""
