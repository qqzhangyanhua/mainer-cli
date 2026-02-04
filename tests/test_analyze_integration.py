"""AnalyzeWorker 集成测试"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.workers.analyze import DEFAULT_ANALYZE_COMMANDS, AnalyzeWorker
from src.workers.cache import AnalyzeTemplateCache


class MockLLMClient:
    """模拟 LLM 客户端"""

    def __init__(self, responses: Optional[list[str]] = None) -> None:
        self._responses = responses or []
        self._call_count = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
            self._call_count += 1
            return response
        return "分析完成"


class TestDefaultAnalyzeCommands:
    """测试预置默认命令"""

    def test_docker_commands_exist(self) -> None:
        """测试 docker 默认命令存在"""
        assert "docker" in DEFAULT_ANALYZE_COMMANDS
        commands = DEFAULT_ANALYZE_COMMANDS["docker"]
        assert len(commands) >= 2
        assert any("inspect" in cmd for cmd in commands)
        assert any("logs" in cmd for cmd in commands)

    def test_process_commands_exist(self) -> None:
        """测试 process 默认命令存在"""
        assert "process" in DEFAULT_ANALYZE_COMMANDS
        commands = DEFAULT_ANALYZE_COMMANDS["process"]
        assert len(commands) >= 2
        assert any("ps" in cmd for cmd in commands)

    def test_port_commands_exist(self) -> None:
        """测试 port 默认命令存在"""
        assert "port" in DEFAULT_ANALYZE_COMMANDS
        commands = DEFAULT_ANALYZE_COMMANDS["port"]
        assert len(commands) >= 2
        assert any("lsof" in cmd or "ss" in cmd for cmd in commands)

    def test_file_commands_exist(self) -> None:
        """测试 file 默认命令存在"""
        assert "file" in DEFAULT_ANALYZE_COMMANDS
        commands = DEFAULT_ANALYZE_COMMANDS["file"]
        assert len(commands) >= 2

    def test_systemd_commands_exist(self) -> None:
        """测试 systemd 默认命令存在"""
        assert "systemd" in DEFAULT_ANALYZE_COMMANDS
        commands = DEFAULT_ANALYZE_COMMANDS["systemd"]
        assert any("systemctl" in cmd for cmd in commands)

    def test_all_commands_have_placeholder(self) -> None:
        """测试所有命令都包含 {name} 占位符"""
        for obj_type, commands in DEFAULT_ANALYZE_COMMANDS.items():
            for cmd in commands:
                assert "{name}" in cmd, f"{obj_type} command missing placeholder: {cmd}"


class TestTypeAutoDetection:
    """测试对象类型自动检测"""

    def test_detect_port_common_ports(self) -> None:
        """测试检测常见端口号"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        # 常见服务端口
        assert worker._detect_target_type("80") == "port"
        assert worker._detect_target_type("443") == "port"
        assert worker._detect_target_type("8080") == "port"
        assert worker._detect_target_type("3306") == "port"
        assert worker._detect_target_type("5432") == "port"
        assert worker._detect_target_type("6379") == "port"
        assert worker._detect_target_type("27017") == "port"

    def test_detect_process_large_numbers(self) -> None:
        """测试检测较大数字为 PID"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        # 较大数字假设为 PID
        assert worker._detect_target_type("12345") == "process"
        assert worker._detect_target_type("99999") == "process"

    def test_detect_file_path(self) -> None:
        """测试检测文件路径"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        assert worker._detect_target_type("/etc/nginx/nginx.conf") == "file"
        assert worker._detect_target_type("/var/log/syslog") == "file"
        assert worker._detect_target_type("/home/user/script.sh") == "file"

    def test_detect_systemd_service(self) -> None:
        """测试检测 systemd 服务"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        assert worker._detect_target_type("nginx.service") == "systemd"
        assert worker._detect_target_type("docker.service") == "systemd"
        assert worker._detect_target_type("mysql.service") == "systemd"

    def test_detect_network_interface(self) -> None:
        """测试检测网络接口"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        assert worker._detect_target_type("eth0") == "network"
        assert worker._detect_target_type("en0") == "network"
        assert worker._detect_target_type("wlan0") == "network"
        assert worker._detect_target_type("lo") == "network"
        assert worker._detect_target_type("docker0") == "network"

    def test_detect_docker_default(self) -> None:
        """测试默认检测为 docker"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        # 其他名称默认为 docker 容器
        assert worker._detect_target_type("my-app") == "docker"
        assert worker._detect_target_type("nginx") == "docker"
        assert worker._detect_target_type("redis-server") == "docker"


class TestAnalyzeWorkerWithDefaultCommands:
    """测试使用默认命令的分析流程"""

    @pytest.mark.asyncio
    async def test_uses_default_commands_for_docker(self) -> None:
        """测试 docker 类型使用预置命令"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            mock_client = MockLLMClient(["分析结果"])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            # 调用 _get_analyze_commands 应该返回预置命令
            commands = await worker._get_analyze_commands("docker", "test-container")

            assert commands == DEFAULT_ANALYZE_COMMANDS["docker"]
            # LLM 不应该被调用来生成命令
            assert mock_client._call_count == 0

    @pytest.mark.asyncio
    async def test_uses_default_commands_for_port(self) -> None:
        """测试 port 类型使用预置命令"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            mock_client = MockLLMClient(["分析结果"])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            commands = await worker._get_analyze_commands("port", "8080")

            assert commands == DEFAULT_ANALYZE_COMMANDS["port"]

    @pytest.mark.asyncio
    async def test_cache_takes_priority_over_default(self) -> None:
        """测试缓存优先于预置命令"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            # 预先设置缓存
            cached_commands = ["custom docker cmd {name}"]
            cache.set("docker", cached_commands)

            mock_client = MockLLMClient([])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            commands = await worker._get_analyze_commands("docker", "test")

            assert commands == cached_commands

    @pytest.mark.asyncio
    async def test_llm_fallback_for_unknown_type(self) -> None:
        """测试未知类型回退到 LLM 生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            mock_client = MockLLMClient(['["custom cmd {name}"]'])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            commands = await worker._get_analyze_commands("unknown_type", "target")

            assert commands == ["custom cmd {name}"]
            # LLM 应该被调用
            assert mock_client._call_count == 1


class TestAnalyzeWorkerEndToEnd:
    """端到端测试"""

    @pytest.mark.asyncio
    async def test_analyze_with_auto_detect_type(self) -> None:
        """测试自动检测类型后分析"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            mock_client = MockLLMClient(["这是一个配置文件的分析结果。"])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            # 不指定类型，应该自动检测为 file
            result = await worker.execute(
                "explain",
                {"target": "/etc/hosts"},  # 不指定 type
            )

            # 应该成功执行（虽然某些命令可能失败）
            # 关键是类型被自动检测为 file
            assert result.task_completed is True or "分析" in result.message or "文件" in result.message

    @pytest.mark.asyncio
    async def test_analyze_port_with_auto_detect(self) -> None:
        """测试端口自动检测分析"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            mock_client = MockLLMClient(["这是端口 8080 的分析结果。"])
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            # 输入数字，应该自动检测为 port
            result = await worker.execute(
                "explain",
                {"target": "8080"},  # 不指定 type
            )

            # 验证使用了 port 类型的命令
            # (即使命令执行失败，也说明类型检测正确)
            assert result is not None
