"""KubernetesWorker 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.types import WorkerResult
from src.workers.kubernetes import KubernetesWorker


@pytest.fixture
def worker() -> KubernetesWorker:
    return KubernetesWorker()


# ------------------------------------------------------------------
# 基础测试
# ------------------------------------------------------------------


def test_worker_name(worker: KubernetesWorker) -> None:
    assert worker.name == "kubernetes"


def test_worker_capabilities(worker: KubernetesWorker) -> None:
    caps = worker.get_capabilities()
    assert "get" in caps
    assert "describe" in caps
    assert "logs" in caps
    assert "top" in caps
    assert "rollout" in caps
    assert "scale" in caps


@pytest.mark.asyncio
async def test_unknown_action(worker: KubernetesWorker) -> None:
    result = await worker.execute("nonexistent", {})
    assert result.success is False


# ------------------------------------------------------------------
# dry-run 测试
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("get", {"resource": "pods", "dry_run": True})
    assert result.success is True
    assert result.simulated is True
    assert "pods" in result.message


@pytest.mark.asyncio
async def test_describe_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("describe", {
        "resource": "pod", "name": "nginx-abc", "dry_run": True,
    })
    assert result.success is True
    assert "nginx-abc" in result.message


@pytest.mark.asyncio
async def test_logs_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("logs", {"pod": "nginx-abc", "dry_run": True})
    assert result.success is True
    assert "nginx-abc" in result.message


@pytest.mark.asyncio
async def test_top_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("top", {"resource": "pods", "dry_run": True})
    assert result.success is True


@pytest.mark.asyncio
async def test_rollout_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("rollout", {
        "subcmd": "restart", "deployment": "web", "dry_run": True,
    })
    assert result.success is True
    assert "web" in result.message


@pytest.mark.asyncio
async def test_scale_dry_run(worker: KubernetesWorker) -> None:
    result = await worker.execute("scale", {
        "deployment": "web", "replicas": 3, "dry_run": True,
    })
    assert result.success is True
    assert "3" in result.message


# ------------------------------------------------------------------
# 参数验证
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_missing_name(worker: KubernetesWorker) -> None:
    result = await worker.execute("describe", {"resource": "pod", "dry_run": True})
    assert result.success is False
    assert "name" in result.message


@pytest.mark.asyncio
async def test_logs_missing_pod(worker: KubernetesWorker) -> None:
    result = await worker.execute("logs", {"dry_run": True})
    assert result.success is False
    assert "pod" in result.message


@pytest.mark.asyncio
async def test_top_invalid_resource(worker: KubernetesWorker) -> None:
    result = await worker.execute("top", {"resource": "deployments", "dry_run": True})
    assert result.success is False
    assert "pods" in result.message or "nodes" in result.message


@pytest.mark.asyncio
async def test_rollout_invalid_subcmd(worker: KubernetesWorker) -> None:
    result = await worker.execute("rollout", {
        "subcmd": "invalid", "deployment": "web", "dry_run": True,
    })
    assert result.success is False


@pytest.mark.asyncio
async def test_rollout_missing_deployment(worker: KubernetesWorker) -> None:
    result = await worker.execute("rollout", {"subcmd": "status", "dry_run": True})
    assert result.success is False
    assert "deployment" in result.message


@pytest.mark.asyncio
async def test_scale_missing_replicas(worker: KubernetesWorker) -> None:
    result = await worker.execute("scale", {"deployment": "web", "dry_run": True})
    assert result.success is False
    assert "replicas" in result.message


# ------------------------------------------------------------------
# _build_cmd 测试
# ------------------------------------------------------------------


def test_build_cmd_basic(worker: KubernetesWorker) -> None:
    cmd = worker._build_cmd("get pods", "")
    assert cmd == "kubectl get pods"


def test_build_cmd_with_namespace(worker: KubernetesWorker) -> None:
    cmd = worker._build_cmd("get pods", "production")
    assert cmd == "kubectl -n production get pods"


def test_build_cmd_with_extra(worker: KubernetesWorker) -> None:
    cmd = worker._build_cmd("get pods", "", "-o json")
    assert cmd == "kubectl get pods -o json"


# ------------------------------------------------------------------
# kubectl 不可用
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_no_kubectl(worker: KubernetesWorker) -> None:
    with patch.object(
        worker._shell,
        "execute",
        new_callable=AsyncMock,
        return_value=WorkerResult(success=False, message="not found"),
    ):
        result = await worker.execute("get", {"resource": "pods"})
        assert result.success is False
        assert "kubectl" in result.message
