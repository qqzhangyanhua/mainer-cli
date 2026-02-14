"""ComposeWorker 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.types import WorkerResult
from src.workers.compose import ComposeWorker


@pytest.fixture
def worker() -> ComposeWorker:
    return ComposeWorker()


# ------------------------------------------------------------------
# 基础测试
# ------------------------------------------------------------------


def test_worker_name(worker: ComposeWorker) -> None:
    assert worker.name == "compose"


def test_worker_capabilities(worker: ComposeWorker) -> None:
    caps = worker.get_capabilities()
    assert "status" in caps
    assert "health" in caps
    assert "logs" in caps
    assert "restart" in caps
    assert "up" in caps
    assert "down" in caps


@pytest.mark.asyncio
async def test_unknown_action(worker: ComposeWorker) -> None:
    result = await worker.execute("nonexistent", {})
    assert result.success is False
    assert "Unknown action" in result.message


# ------------------------------------------------------------------
# dry-run 测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("status", {"dry_run": True})
    assert result.success is True
    assert result.simulated is True
    assert "DRY-RUN" in result.message


@pytest.mark.asyncio
async def test_health_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("health", {"dry_run": True})
    assert result.success is True
    assert result.simulated is True


@pytest.mark.asyncio
async def test_logs_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("logs", {"dry_run": True, "service": "web"})
    assert result.success is True
    assert "web" in result.message


@pytest.mark.asyncio
async def test_restart_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("restart", {"dry_run": True, "service": "api"})
    assert result.success is True
    assert "api" in result.message


@pytest.mark.asyncio
async def test_up_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("up", {"dry_run": True})
    assert result.success is True
    assert "DRY-RUN" in result.message


@pytest.mark.asyncio
async def test_down_dry_run(worker: ComposeWorker) -> None:
    result = await worker.execute("down", {"dry_run": True})
    assert result.success is True
    assert "DRY-RUN" in result.message


# ------------------------------------------------------------------
# _parse_compose_ps 测试
# ------------------------------------------------------------------


def test_parse_empty_output() -> None:
    services = ComposeWorker._parse_compose_ps("")
    assert services == []


def test_parse_single_service() -> None:
    raw = '{"Name":"myapp-web-1","Service":"web","State":"running","Image":"nginx:latest","Ports":"0.0.0.0:80->80/tcp","Health":""}\n'
    services = ComposeWorker._parse_compose_ps(raw)
    assert len(services) == 1
    assert services[0]["name"] == "myapp-web-1"
    assert services[0]["service"] == "web"
    assert services[0]["state"] == "running"
    assert services[0]["image"] == "nginx:latest"


def test_parse_multiple_services() -> None:
    raw = (
        '{"Name":"app-web-1","Service":"web","State":"running","Image":"nginx","Ports":"","Health":""}\n'
        '{"Name":"app-db-1","Service":"db","State":"running","Image":"postgres","Ports":"","Health":"healthy"}\n'
        '{"Name":"app-redis-1","Service":"redis","State":"exited (0)","Image":"redis","Ports":"","Health":""}\n'
    )
    services = ComposeWorker._parse_compose_ps(raw)
    assert len(services) == 3
    assert services[0]["state"] == "running"
    assert services[1]["health"] == "healthy"
    assert services[2]["state"] == "exited"


def test_parse_invalid_json_line() -> None:
    raw = '{"Name":"ok","Service":"web","State":"running","Image":"nginx","Ports":"","Health":""}\nnot-json\n'
    services = ComposeWorker._parse_compose_ps(raw)
    assert len(services) == 1


# ------------------------------------------------------------------
# _build_cmd 测试
# ------------------------------------------------------------------


def test_build_cmd_basic(worker: ComposeWorker) -> None:
    cmd = worker._build_cmd("docker compose", "", "", "ps")
    assert cmd == "docker compose ps"


def test_build_cmd_with_project(worker: ComposeWorker) -> None:
    cmd = worker._build_cmd("docker compose", "myapp", "", "ps")
    assert cmd == "docker compose -p myapp ps"


def test_build_cmd_with_file(worker: ComposeWorker) -> None:
    cmd = worker._build_cmd("docker compose", "", "docker-compose.prod.yml", "up -d")
    assert cmd == "docker compose -f docker-compose.prod.yml up -d"


def test_build_cmd_with_both(worker: ComposeWorker) -> None:
    cmd = worker._build_cmd(
        "docker-compose", "myapp", "docker-compose.yml", "logs --tail 50"
    )
    assert cmd == "docker-compose -f docker-compose.yml -p myapp logs --tail 50"


# ------------------------------------------------------------------
# _detect_compose_cmd 测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_compose_v2(worker: ComposeWorker) -> None:
    with patch.object(
        worker._shell,
        "execute",
        new_callable=AsyncMock,
        return_value=WorkerResult(success=True, message="Docker Compose version v2.20.0"),
    ):
        cmd = await worker._detect_compose_cmd()
        assert cmd == "docker compose"


@pytest.mark.asyncio
async def test_detect_compose_v1(worker: ComposeWorker) -> None:
    call_count = 0

    async def side_effect(action: str, args: dict) -> WorkerResult:  # type: ignore[type-arg]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return WorkerResult(success=False, message="not found")
        return WorkerResult(success=True, message="docker-compose version 1.29.2")

    with patch.object(worker._shell, "execute", side_effect=side_effect):
        cmd = await worker._detect_compose_cmd()
        assert cmd == "docker-compose"


@pytest.mark.asyncio
async def test_detect_compose_not_found(worker: ComposeWorker) -> None:
    with patch.object(
        worker._shell,
        "execute",
        new_callable=AsyncMock,
        return_value=WorkerResult(success=False, message="not found"),
    ):
        cmd = await worker._detect_compose_cmd()
        assert cmd == ""


# ------------------------------------------------------------------
# compose 不可用时的处理
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_no_compose(worker: ComposeWorker) -> None:
    with patch.object(
        worker._shell,
        "execute",
        new_callable=AsyncMock,
        return_value=WorkerResult(success=False, message="not found"),
    ):
        result = await worker.execute("status", {})
        assert result.success is False
        assert "未找到" in result.message
