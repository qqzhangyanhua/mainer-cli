"""错误提示助手测试"""

import pytest

from src.orchestrator.error_helper import ErrorHelper
from src.types import WorkerResult


class TestErrorHelperBasic:
    """基础测试"""

    def test_success_result_returns_none(self) -> None:
        """成功结果不返回建议"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=True,
            message="Operation completed",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is None

    def test_generic_error_returns_suggestions(self) -> None:
        """普通错误返回通用建议"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Something went wrong",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "操作失败" in suggestions
        assert "dry-run" in suggestions


class TestContainerNotFound:
    """容器未找到错误测试"""

    def test_container_not_found(self) -> None:
        """容器未找到错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: No such container: my_app",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "容器名称错误" in suggestions
        assert "列出所有容器" in suggestions

    def test_docker_not_found(self) -> None:
        """Docker 容器未找到"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error response from daemon: container not found",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "容器" in suggestions


class TestPermissionDenied:
    """权限不足错误测试"""

    def test_permission_denied(self) -> None:
        """权限不足错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Permission denied: /etc/passwd",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "权限不足" in suggestions
        assert "sudo" in suggestions

    def test_docker_permission(self) -> None:
        """Docker 权限错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Got permission denied while trying to connect to the Docker daemon socket",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "docker" in suggestions.lower()


class TestPortInUse:
    """端口占用错误测试"""

    def test_address_already_in_use(self) -> None:
        """端口占用错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: address already in use :8080",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "8080" in suggestions
        assert "端口" in suggestions

    def test_bind_port_error(self) -> None:
        """绑定端口错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: bind: port 3000 is already in use",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "3000" in suggestions


class TestFileNotFound:
    """文件不存在错误测试"""

    def test_no_such_file(self) -> None:
        """文件不存在"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: no such file or directory: /path/to/file",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "文件/目录不存在" in suggestions

    def test_does_not_exist(self) -> None:
        """目录不存在"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: /var/log/app.log does not exist",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "检查路径" in suggestions

    def test_enoent(self) -> None:
        """ENOENT 错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="ENOENT: no such file or directory",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "文件" in suggestions


class TestDockerNotRunning:
    """Docker 未运行错误测试"""

    def test_docker_daemon_not_running(self) -> None:
        """Docker daemon 未运行"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "Docker 未运行" in suggestions
        assert "systemctl start docker" in suggestions


class TestCommandNotFound:
    """命令未找到错误测试"""

    def test_command_not_found_format1(self) -> None:
        """命令未找到格式1"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="bash: kubectl: command not found",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "kubectl" in suggestions
        assert "apt install" in suggestions

    def test_command_not_found_format2(self) -> None:
        """命令未找到格式2"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="command not found: docker-compose",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "docker-compose" in suggestions


class TestNetworkError:
    """网络错误测试"""

    def test_connection_refused(self) -> None:
        """连接被拒绝"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: Connection refused to localhost:5432",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "网络连接失败" in suggestions

    def test_connection_timed_out(self) -> None:
        """连接超时"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: Connection timed out",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "网络" in suggestions

    def test_dns_error(self) -> None:
        """DNS 解析错误"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: DNS name resolution failed",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "DNS" in suggestions


class TestDiskFull:
    """磁盘空间不足错误测试"""

    def test_no_space_left(self) -> None:
        """无剩余空间"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: No space left on device",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "磁盘空间不足" in suggestions
        assert "docker system prune" in suggestions

    def test_disk_quota_exceeded(self) -> None:
        """磁盘配额超出"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: Disk quota exceeded",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "磁盘" in suggestions


class TestGitError:
    """Git 错误测试"""

    def test_not_a_git_repository(self) -> None:
        """不是 Git 仓库"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="fatal: not a git repository",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "Git 仓库" in suggestions
        assert "git init" in suggestions

    def test_authentication_failed(self) -> None:
        """Git 认证失败"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="fatal: Authentication failed for git repository",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "认证失败" in suggestions
        assert "SSH" in suggestions

    def test_merge_conflict(self) -> None:
        """Git 合并冲突"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="error: git merge conflict in file.txt",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "合并冲突" in suggestions

    def test_directory_already_exists(self) -> None:
        """目录已存在"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="fatal: destination path 'repo' already exists and is not an empty directory. git clone failed",
        )
        suggestions = helper.suggest_fix(result)
        assert suggestions is not None
        assert "已存在" in suggestions


class TestEnhanceErrorMessage:
    """增强错误消息测试"""

    def test_enhance_success_message_unchanged(self) -> None:
        """成功消息不变"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=True,
            message="Done",
        )
        enhanced = helper.enhance_error_message(result)
        assert enhanced.message == "Done"
        assert enhanced.success is True

    def test_enhance_error_message_with_suggestions(self) -> None:
        """错误消息附加建议"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error: No such container",
        )
        enhanced = helper.enhance_error_message(result)
        assert "No such container" in enhanced.message
        assert "容器名称错误" in enhanced.message
        assert enhanced.success is False

    def test_enhance_preserves_other_fields(self) -> None:
        """增强保留其他字段"""
        helper = ErrorHelper()
        result = WorkerResult(
            success=False,
            message="Error",
            data={"key": "value"},
            task_completed=False,
            simulated=True,
        )
        enhanced = helper.enhance_error_message(result)
        assert enhanced.data == {"key": "value"}
        assert enhanced.task_completed is False
        assert enhanced.simulated is True


class TestPortExtraction:
    """端口提取测试"""

    def test_extract_port_from_colon_format(self) -> None:
        """从冒号格式提取端口"""
        port = ErrorHelper._extract_port("address already in use :8080")
        assert port == "8080"

    def test_extract_port_from_word_format(self) -> None:
        """从单词格式提取端口"""
        port = ErrorHelper._extract_port("bind to port 3000 failed")
        assert port == "3000"

    def test_extract_port_fallback(self) -> None:
        """无法提取时返回占位符"""
        port = ErrorHelper._extract_port("port is busy")
        assert port == "<端口号>"


class TestCommandExtraction:
    """命令提取测试"""

    def test_extract_command_format1(self) -> None:
        """命令提取格式1"""
        cmd = ErrorHelper._extract_command("command not found: kubectl")
        assert cmd == "kubectl"

    def test_extract_command_format2(self) -> None:
        """命令提取格式2"""
        cmd = ErrorHelper._extract_command("docker: command not found")
        assert cmd == "docker"

    def test_extract_command_fallback(self) -> None:
        """无法提取时返回占位符"""
        cmd = ErrorHelper._extract_command("not found")
        assert cmd == "<命令>"
