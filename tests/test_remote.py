"""RemoteWorker 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.manager import RemoteConfig
from src.types import HostConfig
from src.workers.remote import RemoteWorker


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def remote_config() -> RemoteConfig:
    return RemoteConfig(
        hosts=[
            HostConfig(
                address="192.168.1.100",
                port=22,
                user="deploy",
                key_path="~/.ssh/id_rsa",
                labels=["web", "production"],
            ),
            HostConfig(
                address="10.0.0.5",
                port=2222,
                user="root",
                labels=["db"],
            ),
        ],
        default_key_path="~/.ssh/id_ed25519",
        connect_timeout=5,
        command_timeout=15,
    )


@pytest.fixture
def worker(remote_config: RemoteConfig) -> RemoteWorker:
    return RemoteWorker(config=remote_config)


@pytest.fixture
def empty_worker() -> RemoteWorker:
    return RemoteWorker(config=RemoteConfig())


# ------------------------------------------------------------------
# 基础测试
# ------------------------------------------------------------------


def test_worker_name(worker: RemoteWorker) -> None:
    assert worker.name == "remote"


def test_worker_capabilities(worker: RemoteWorker) -> None:
    caps = worker.get_capabilities()
    assert "execute" in caps
    assert "list_hosts" in caps
    assert "test_connection" in caps


@pytest.mark.asyncio
async def test_unknown_action(worker: RemoteWorker) -> None:
    result = await worker.execute("nonexistent", {})
    assert result.success is False
    assert "Unknown action" in result.message


# ------------------------------------------------------------------
# list_hosts 测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_hosts(worker: RemoteWorker) -> None:
    result = await worker.execute("list_hosts", {})
    assert result.success is True
    assert "192.168.1.100" in result.message
    assert "10.0.0.5" in result.message
    assert result.task_completed is True


@pytest.mark.asyncio
async def test_list_hosts_empty(empty_worker: RemoteWorker) -> None:
    result = await empty_worker.execute("list_hosts", {})
    assert result.success is True
    assert "未配置" in result.message


# ------------------------------------------------------------------
# 主机解析测试
# ------------------------------------------------------------------


def test_resolve_host_by_address(worker: RemoteWorker) -> None:
    host = worker._resolve_host("192.168.1.100")
    assert host is not None
    assert host.user == "deploy"


def test_resolve_host_by_label(worker: RemoteWorker) -> None:
    host = worker._resolve_host("db")
    assert host is not None
    assert host.address == "10.0.0.5"


def test_resolve_host_not_found(worker: RemoteWorker) -> None:
    host = worker._resolve_host("nonexistent")
    assert host is None


def test_resolve_key_path_from_host(worker: RemoteWorker) -> None:
    host = worker._resolve_host("192.168.1.100")
    assert host is not None
    key_path = worker._resolve_key_path(host)
    assert key_path is not None
    assert "id_rsa" in key_path


def test_resolve_key_path_fallback_to_default(worker: RemoteWorker) -> None:
    """主机未配置私钥时使用默认路径"""
    host = worker._resolve_host("10.0.0.5")
    assert host is not None
    assert host.key_path is None
    key_path = worker._resolve_key_path(host)
    assert key_path is not None
    assert "id_ed25519" in key_path


# ------------------------------------------------------------------
# execute 参数验证测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_missing_host(worker: RemoteWorker) -> None:
    result = await worker.execute("execute", {"command": "ls"})
    assert result.success is False
    assert "host" in result.message


@pytest.mark.asyncio
async def test_execute_missing_command(worker: RemoteWorker) -> None:
    result = await worker.execute("execute", {"host": "192.168.1.100"})
    assert result.success is False
    assert "command" in result.message


@pytest.mark.asyncio
async def test_execute_unknown_host(worker: RemoteWorker) -> None:
    result = await worker.execute("execute", {
        "host": "unknown-host",
        "command": "ls",
    })
    assert result.success is False
    assert "未找到主机" in result.message


@pytest.mark.asyncio
async def test_execute_dry_run(worker: RemoteWorker) -> None:
    result = await worker.execute("execute", {
        "host": "192.168.1.100",
        "command": "df -h",
        "dry_run": True,
    })
    assert result.success is True
    assert result.simulated is True
    assert "DRY-RUN" in result.message
    assert "192.168.1.100" in result.message
    assert "df -h" in result.message


# ------------------------------------------------------------------
# test_connection 参数验证测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_missing_host(worker: RemoteWorker) -> None:
    result = await worker.execute("test_connection", {})
    assert result.success is False
    assert "host" in result.message


@pytest.mark.asyncio
async def test_connection_unknown_host(worker: RemoteWorker) -> None:
    result = await worker.execute("test_connection", {"host": "unknown"})
    assert result.success is False
    assert "未找到主机" in result.message


# ------------------------------------------------------------------
# 输出截断测试
# ------------------------------------------------------------------


def test_truncate_short_output(worker: RemoteWorker) -> None:
    output, truncated = worker._truncate_output("hello")
    assert output == "hello"
    assert truncated is False


def test_truncate_long_output(worker: RemoteWorker) -> None:
    long_output = "x" * 5000
    output, truncated = worker._truncate_output(long_output)
    assert truncated is True
    assert "truncated" in output
    assert len(output) < len(long_output)


# ------------------------------------------------------------------
# PolicyEngine 远程风险升级测试
# ------------------------------------------------------------------


def test_remote_execute_minimum_medium_risk() -> None:
    from src.orchestrator.policy_engine import PolicyEngine
    from src.types import Instruction

    instruction = Instruction(
        worker="remote",
        action="execute",
        args={"host": "192.168.1.100", "command": "ls -la"},
        risk_level="safe",
    )
    result = PolicyEngine.check_instruction(instruction)
    assert result.risk_level == "medium"


def test_remote_execute_high_risk_pattern() -> None:
    from src.orchestrator.policy_engine import PolicyEngine
    from src.types import Instruction

    instruction = Instruction(
        worker="remote",
        action="execute",
        args={"host": "192.168.1.100", "command": "rm -rf /tmp/old"},
        risk_level="safe",
    )
    result = PolicyEngine.check_instruction(instruction)
    assert result.risk_level == "high"


def test_remote_list_hosts_safe_risk() -> None:
    from src.orchestrator.policy_engine import PolicyEngine
    from src.types import Instruction

    instruction = Instruction(
        worker="remote",
        action="list_hosts",
        args={},
        risk_level="safe",
    )
    result = PolicyEngine.check_instruction(instruction)
    assert result.risk_level == "safe"
