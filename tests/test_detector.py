"""环境检测器测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.context.detector import EnvironmentDetector, EnvironmentInfo


class TestEnvironmentInfo:
    """测试 EnvironmentInfo 数据类"""

    def test_create_environment_info(self) -> None:
        """测试创建环境信息对象"""
        info = EnvironmentInfo(
            has_docker=True,
            docker_containers=3,
            has_systemd=True,
            systemd_services=["nginx", "mysql"],
            has_kubernetes=False,
            disk_usage=75.5,
            memory_usage=60.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        assert info.has_docker is True
        assert info.docker_containers == 3
        assert info.has_systemd is True
        assert info.systemd_services == ["nginx", "mysql"]
        assert info.has_kubernetes is False
        assert info.disk_usage == 75.5
        assert info.memory_usage == 60.0
        assert info.os_type == "Linux"
        assert info.os_version == "5.15.0"


class TestEnvironmentDetector:
    """测试 EnvironmentDetector"""

    def test_detect_returns_environment_info(self) -> None:
        """测试 detect 方法返回 EnvironmentInfo"""
        detector = EnvironmentDetector()
        info = detector.detect()

        assert isinstance(info, EnvironmentInfo)
        assert isinstance(info.has_docker, bool)
        assert isinstance(info.docker_containers, int)
        assert isinstance(info.has_systemd, bool)
        assert isinstance(info.systemd_services, list)
        assert isinstance(info.has_kubernetes, bool)
        assert isinstance(info.disk_usage, float)
        assert isinstance(info.memory_usage, float)
        assert isinstance(info.os_type, str)
        assert isinstance(info.os_version, str)

    @patch("subprocess.run")
    def test_check_docker_available(self, mock_run: MagicMock) -> None:
        """测试 Docker 可用时的检测"""
        mock_run.return_value = MagicMock(returncode=0)
        detector = EnvironmentDetector()

        assert detector._check_docker() is True
        mock_run.assert_called_with(
            ["docker", "ps"],
            capture_output=True,
            timeout=3,
            check=False,
        )

    @patch("subprocess.run")
    def test_check_docker_not_available(self, mock_run: MagicMock) -> None:
        """测试 Docker 不可用时的检测"""
        mock_run.return_value = MagicMock(returncode=1)
        detector = EnvironmentDetector()

        assert detector._check_docker() is False

    @patch("subprocess.run")
    def test_check_docker_not_installed(self, mock_run: MagicMock) -> None:
        """测试 Docker 未安装时的检测"""
        mock_run.side_effect = FileNotFoundError()
        detector = EnvironmentDetector()

        assert detector._check_docker() is False

    @patch("subprocess.run")
    def test_count_containers(self, mock_run: MagicMock) -> None:
        """测试容器计数"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123\ndef456\nghi789\n",
        )
        detector = EnvironmentDetector()

        assert detector._count_containers() == 3

    @patch("subprocess.run")
    def test_count_containers_empty(self, mock_run: MagicMock) -> None:
        """测试无容器时的计数"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
        )
        detector = EnvironmentDetector()

        assert detector._count_containers() == 0

    @patch("subprocess.run")
    def test_check_systemd_available(self, mock_run: MagicMock) -> None:
        """测试 Systemd 可用时的检测"""
        mock_run.return_value = MagicMock(returncode=0)
        detector = EnvironmentDetector()

        assert detector._check_systemd() is True

    @patch("subprocess.run")
    def test_check_systemd_not_available(self, mock_run: MagicMock) -> None:
        """测试 Systemd 不可用时的检测"""
        mock_run.side_effect = FileNotFoundError()
        detector = EnvironmentDetector()

        assert detector._check_systemd() is False

    @patch("subprocess.run")
    def test_check_kubernetes_available(self, mock_run: MagicMock) -> None:
        """测试 Kubernetes 可用时的检测"""
        mock_run.return_value = MagicMock(returncode=0)
        detector = EnvironmentDetector()

        assert detector._check_kubernetes() is True

    @patch("subprocess.run")
    def test_check_kubernetes_not_available(self, mock_run: MagicMock) -> None:
        """测试 Kubernetes 不可用时的检测"""
        mock_run.side_effect = FileNotFoundError()
        detector = EnvironmentDetector()

        assert detector._check_kubernetes() is False


class TestGenerateSuggestions:
    """测试建议生成"""

    def test_suggestions_with_docker_containers(self) -> None:
        """测试有 Docker 容器时的建议"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=True,
            docker_containers=5,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        suggestions = detector.generate_suggestions(info)

        assert len(suggestions) == 3
        assert "查看所有容器状态" in suggestions

    def test_suggestions_with_high_disk_usage(self) -> None:
        """测试磁盘使用率高时的建议"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=85.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        suggestions = detector.generate_suggestions(info)

        assert "查看磁盘使用情况" in suggestions

    def test_suggestions_with_systemd_services(self) -> None:
        """测试有 Systemd 服务时的建议"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=True,
            systemd_services=["nginx", "mysql"],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        suggestions = detector.generate_suggestions(info)

        assert any("nginx" in s for s in suggestions)

    def test_suggestions_always_returns_three(self) -> None:
        """测试始终返回 3 个建议"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        suggestions = detector.generate_suggestions(info)

        assert len(suggestions) == 3


class TestGenerateWelcomeMessage:
    """测试欢迎消息生成"""

    def test_welcome_message_contains_os_info(self) -> None:
        """测试欢迎消息包含操作系统信息"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        message = detector.generate_welcome_message(info)

        assert "Linux" in message
        assert "5.15.0" in message

    def test_welcome_message_shows_docker_status(self) -> None:
        """测试欢迎消息显示 Docker 状态"""
        detector = EnvironmentDetector()

        # Docker 运行中
        info_with_docker = EnvironmentInfo(
            has_docker=True,
            docker_containers=3,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )
        message = detector.generate_welcome_message(info_with_docker)
        assert "Docker 正在运行" in message
        assert "3 个运行中" in message

        # Docker 未运行
        info_without_docker = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )
        message = detector.generate_welcome_message(info_without_docker)
        assert "Docker 未运行" in message

    def test_welcome_message_shows_disk_warning(self) -> None:
        """测试高磁盘使用率时显示警告"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=85.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        message = detector.generate_welcome_message(info)

        assert "85%" in message
        assert "建议清理" in message

    def test_welcome_message_includes_suggestions(self) -> None:
        """测试欢迎消息包含建议"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=True,
            docker_containers=2,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        message = detector.generate_welcome_message(info)

        assert "推荐你试试这些操作" in message
        assert "1." in message  # 至少有一个建议

    def test_welcome_message_includes_tips(self) -> None:
        """测试欢迎消息包含提示"""
        detector = EnvironmentDetector()
        info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        message = detector.generate_welcome_message(info)

        assert "自然语言" in message
        assert "查看日志" in message
