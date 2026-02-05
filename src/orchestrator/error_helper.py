"""错误提示助手

分析 Worker 执行失败的结果，生成可操作的修复建议。
"""

from __future__ import annotations

import re
from typing import List, Optional

from src.types import WorkerResult


class ErrorHelper:
    """错误提示助手

    根据错误类型生成针对性的修复建议。
    """

    def suggest_fix(self, result: WorkerResult, user_input: str = "") -> Optional[str]:
        """根据错误结果生成建议

        Args:
            result: Worker 执行结果
            user_input: 用户原始输入（可选）

        Returns:
            建议文本（如果有）
        """
        if result.success:
            return None

        error_msg = result.message.lower()
        suggestions: List[str] = []

        # 命令未找到（优先级最高，避免被其他 "not found" 规则捕获）
        if "command not found" in error_msg:
            cmd = self._extract_command(error_msg)
            suggestions = self._suggest_command_not_found(cmd)

        # 容器未找到
        elif self._is_container_not_found(error_msg):
            suggestions = self._suggest_container_not_found()

        # 权限不足
        elif "permission denied" in error_msg:
            suggestions = self._suggest_permission_denied()

        # 端口占用
        elif self._is_port_in_use(error_msg):
            port = self._extract_port(error_msg)
            suggestions = self._suggest_port_in_use(port)

        # Docker 未运行
        elif "cannot connect to the docker daemon" in error_msg:
            suggestions = self._suggest_docker_not_running()

        # 文件不存在（优先级最低，因为 "not found" 是通用匹配）
        elif self._is_file_not_found(error_msg):
            suggestions = self._suggest_file_not_found()

        # 网络错误
        elif self._is_network_error(error_msg):
            suggestions = self._suggest_network_error()

        # 磁盘空间不足
        elif self._is_disk_full(error_msg):
            suggestions = self._suggest_disk_full()

        # Git 相关错误
        elif self._is_git_error(error_msg):
            suggestions = self._suggest_git_error(error_msg)

        # 通用建议
        if not suggestions:
            suggestions = self._suggest_generic()

        return "\n".join(suggestions)

    @staticmethod
    def _is_container_not_found(error_msg: str) -> bool:
        """检查是否为容器未找到错误"""
        return (
            "not found" in error_msg
            and ("container" in error_msg or "docker" in error_msg)
        ) or "no such container" in error_msg

    @staticmethod
    def _suggest_container_not_found() -> List[str]:
        """容器未找到的建议"""
        return [
            "可能的原因：",
            "  1. 容器名称错误，使用以下命令查看所有容器：",
            "     > 列出所有容器",
            "  2. 容器可能已停止，查看包括停止的容器：",
            "     > docker ps -a",
            "  3. 如果是 systemd 服务，尝试：",
            "     > 查看服务状态",
        ]

    @staticmethod
    def _suggest_permission_denied() -> List[str]:
        """权限不足的建议"""
        return [
            "权限不足，尝试以下方法：",
            "  1. 检查文件/目录权限：",
            "     ls -la <文件路径>",
            "  2. 如果需要 root 权限，使用 sudo：",
            "     sudo opsai-tui",
            "  3. 对于 Docker，确保用户在 docker 组：",
            "     sudo usermod -aG docker $USER",
            "     注意：需要重新登录后生效",
        ]

    @staticmethod
    def _is_port_in_use(error_msg: str) -> bool:
        """检查是否为端口占用错误"""
        return "address already in use" in error_msg or (
            "bind" in error_msg and "port" in error_msg
        )

    @staticmethod
    def _extract_port(error_msg: str) -> str:
        """从错误消息中提取端口号"""
        port_match = re.search(r":(\d{2,5})", error_msg)
        if port_match:
            return port_match.group(1)
        port_match = re.search(r"port\s*(\d{2,5})", error_msg)
        if port_match:
            return port_match.group(1)
        return "<端口号>"

    @staticmethod
    def _suggest_port_in_use(port: str) -> List[str]:
        """端口占用的建议"""
        return [
            f"端口 {port} 已被占用，尝试以下方法：",
            f"  1. 查看占用端口的进程：",
            f"     > 查看 {port} 端口占用",
            f"     或使用: lsof -i :{port}",
            f"  2. 停止占用进程后重试",
            f"  3. 修改服务配置，使用其他端口",
        ]

    @staticmethod
    def _is_file_not_found(error_msg: str) -> bool:
        """检查是否为文件不存在错误"""
        return (
            "no such file" in error_msg
            or "not found" in error_msg
            or "does not exist" in error_msg
            or "enoent" in error_msg
        )

    @staticmethod
    def _suggest_file_not_found() -> List[str]:
        """文件不存在的建议"""
        return [
            "文件/目录不存在，尝试以下方法：",
            "  1. 检查路径是否正确（注意大小写）",
            "  2. 查看当前目录内容：",
            "     > 列出当前目录文件",
            "  3. 搜索文件位置：",
            "     > 查找文件 <文件名>",
        ]

    @staticmethod
    def _suggest_docker_not_running() -> List[str]:
        """Docker 未运行的建议"""
        return [
            "Docker 未运行，尝试以下方法：",
            "  1. Linux 启动 Docker：",
            "     sudo systemctl start docker",
            "  2. 检查 Docker 状态：",
            "     sudo systemctl status docker",
            "  3. macOS/Windows 请启动 Docker Desktop 应用",
        ]

    @staticmethod
    def _extract_command(error_msg: str) -> str:
        """从错误消息中提取命令名"""
        # 支持带连字符的命令名，如 docker-compose
        cmd_match = re.search(r"command not found:\s*([\w\-]+)", error_msg)
        if cmd_match:
            return cmd_match.group(1)
        cmd_match = re.search(r"([\w\-]+):\s*command not found", error_msg)
        if cmd_match:
            return cmd_match.group(1)
        return "<命令>"

    @staticmethod
    def _suggest_command_not_found(cmd: str) -> List[str]:
        """命令未找到的建议"""
        return [
            f"命令 '{cmd}' 未安装，尝试以下方法：",
            f"  1. 安装命令（根据系统）：",
            f"     apt install {cmd}   # Debian/Ubuntu",
            f"     yum install {cmd}   # CentOS/RHEL",
            f"     brew install {cmd}  # macOS",
            f"  2. 检查命令是否在 PATH 中：",
            f"     which {cmd}",
        ]

    @staticmethod
    def _is_network_error(error_msg: str) -> bool:
        """检查是否为网络错误"""
        return (
            "connection refused" in error_msg
            or "connection timed out" in error_msg
            or "network unreachable" in error_msg
            or "no route to host" in error_msg
            or "name resolution" in error_msg
            or "dns" in error_msg
        )

    @staticmethod
    def _suggest_network_error() -> List[str]:
        """网络错误的建议"""
        return [
            "网络连接失败，尝试以下方法：",
            "  1. 检查网络连接：",
            "     ping 8.8.8.8",
            "  2. 检查 DNS 解析：",
            "     nslookup <域名>",
            "  3. 检查防火墙设置",
            "  4. 如果使用代理，检查代理配置",
        ]

    @staticmethod
    def _is_disk_full(error_msg: str) -> bool:
        """检查是否为磁盘空间不足错误"""
        return (
            "no space left" in error_msg
            or "disk quota exceeded" in error_msg
            or "enospc" in error_msg
        )

    @staticmethod
    def _suggest_disk_full() -> List[str]:
        """磁盘空间不足的建议"""
        return [
            "磁盘空间不足，尝试以下方法：",
            "  1. 查看磁盘使用情况：",
            "     > 查看磁盘空间",
            "  2. 查找大文件：",
            "     > 查找大文件",
            "  3. 清理 Docker 资源：",
            "     docker system prune -a",
            "  4. 清理日志文件：",
            "     > 清理日志",
        ]

    @staticmethod
    def _is_git_error(error_msg: str) -> bool:
        """检查是否为 Git 错误"""
        return "git" in error_msg and (
            "not a git repository" in error_msg
            or "authentication failed" in error_msg
            or "merge conflict" in error_msg
            or "already exists" in error_msg
        )

    @staticmethod
    def _suggest_git_error(error_msg: str) -> List[str]:
        """Git 错误的建议"""
        if "not a git repository" in error_msg:
            return [
                "不是 Git 仓库，尝试以下方法：",
                "  1. 初始化 Git 仓库：",
                "     git init",
                "  2. 切换到正确的目录：",
                "     cd <项目目录>",
            ]
        elif "authentication failed" in error_msg:
            return [
                "Git 认证失败，尝试以下方法：",
                "  1. 检查 Git 凭据：",
                "     git config --global credential.helper",
                "  2. 使用 SSH 而非 HTTPS：",
                "     git remote set-url origin git@github.com:<user>/<repo>.git",
                "  3. 生成新的 SSH 密钥或 Token",
            ]
        elif "merge conflict" in error_msg:
            return [
                "Git 合并冲突，尝试以下方法：",
                "  1. 查看冲突文件：",
                "     git status",
                "  2. 手动解决冲突后提交",
                "  3. 放弃合并：",
                "     git merge --abort",
            ]
        elif "already exists" in error_msg:
            return [
                "目录已存在，尝试以下方法：",
                "  1. 使用其他目录名",
                "  2. 删除已存在的目录后重试",
                "  3. 如果要更新，使用 git pull",
            ]
        return []

    @staticmethod
    def _suggest_generic() -> List[str]:
        """通用建议"""
        return [
            "操作失败，建议：",
            "  1. 检查输入是否正确",
            "  2. 使用 --dry-run 预览操作：",
            "     opsai query '...' --dry-run",
            "  3. 查看审计日志了解详情：",
            "     cat ~/.opsai/audit.log",
            "  4. 输入 /help 查看可用命令",
        ]

    def enhance_error_message(
        self, result: WorkerResult, user_input: str = ""
    ) -> WorkerResult:
        """增强错误消息，附加建议

        Args:
            result: Worker 执行结果
            user_input: 用户原始输入

        Returns:
            增强后的 WorkerResult
        """
        if result.success:
            return result

        suggestions = self.suggest_fix(result, user_input)
        if suggestions:
            enhanced_message = f"{result.message}\n\n{suggestions}"
            return WorkerResult(
                success=result.success,
                data=result.data,
                message=enhanced_message,
                task_completed=result.task_completed,
                simulated=result.simulated,
            )

        return result
