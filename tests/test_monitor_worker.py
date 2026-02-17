"""MonitorWorker 单元测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.monitor import MonitorWorker


class TestMonitorWorker:
    """MonitorWorker 测试类"""

    @pytest.fixture
    def worker(self) -> MonitorWorker:
        return MonitorWorker()

    def test_name(self, worker: MonitorWorker) -> None:
        assert worker.name == "monitor"

    def test_capabilities(self, worker: MonitorWorker) -> None:
        caps = worker.get_capabilities()
        assert "snapshot" in caps
        assert "check_port" in caps
        assert "check_http" in caps
        assert "check_process" in caps

    @pytest.mark.asyncio
    async def test_unknown_action(self, worker: MonitorWorker) -> None:
        result = await worker.execute("unknown_action", {})
        assert result.success is False
        assert "Unknown action" in result.message

    # ------------------------------------------------------------------
    # dry-run 测试
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_snapshot_dry_run(self, worker: MonitorWorker) -> None:
        result = await worker.execute("snapshot", {"dry_run": True})
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_check_port_dry_run(self, worker: MonitorWorker) -> None:
        result = await worker.execute("check_port", {"port": 8080, "dry_run": True})
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_check_http_dry_run(self, worker: MonitorWorker) -> None:
        result = await worker.execute(
            "check_http", {"url": "http://localhost:8080", "dry_run": True}
        )
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    @pytest.mark.asyncio
    async def test_check_process_dry_run(self, worker: MonitorWorker) -> None:
        result = await worker.execute("check_process", {"name": "python", "dry_run": True})
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    # ------------------------------------------------------------------
    # snapshot 真实逻辑（mock psutil）
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_snapshot_real(self, worker: MonitorWorker) -> None:
        mock_mem = MagicMock()
        mock_mem.percent = 45.0
        mock_mem.used = 4 * 1024**3  # 4GB
        mock_mem.total = 16 * 1024**3  # 16GB

        mock_part = MagicMock()
        mock_part.mountpoint = "/"

        mock_disk = MagicMock()
        mock_disk.percent = 60.0
        mock_disk.used = 100 * 1024**3
        mock_disk.total = 500 * 1024**3

        with (
            patch("src.workers.monitor.psutil.cpu_percent", return_value=25.0),
            patch("src.workers.monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.workers.monitor.psutil.disk_partitions", return_value=[mock_part]),
            patch("src.workers.monitor.psutil.disk_usage", return_value=mock_disk),
            patch("src.workers.monitor.psutil.getloadavg", return_value=(1.5, 1.2, 0.9)),
            patch("src.workers.monitor.psutil.cpu_count", return_value=8),
        ):
            result = await worker.execute("snapshot", {})

        assert result.success is True
        assert result.task_completed is True
        assert isinstance(result.data, list)
        assert len(result.data) == 4  # cpu, memory, disk, load

        names = [d["name"] for d in result.data]
        assert "cpu_usage" in names
        assert "memory_usage" in names
        assert "disk_/" in names
        assert "load_average" in names

        # CPU 25% → ok
        cpu_entry = next(d for d in result.data if d["name"] == "cpu_usage")
        assert cpu_entry["status"] == "ok"

    @pytest.mark.asyncio
    async def test_snapshot_warning_threshold(self, worker: MonitorWorker) -> None:
        """CPU 85% 应触发 warning"""
        mock_mem = MagicMock()
        mock_mem.percent = 45.0
        mock_mem.used = 4 * 1024**3
        mock_mem.total = 16 * 1024**3

        with (
            patch("src.workers.monitor.psutil.cpu_percent", return_value=85.0),
            patch("src.workers.monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.workers.monitor.psutil.disk_partitions", return_value=[]),
            patch("src.workers.monitor.psutil.getloadavg", return_value=(0.5, 0.5, 0.5)),
            patch("src.workers.monitor.psutil.cpu_count", return_value=4),
        ):
            result = await worker.execute("snapshot", {"include": ["cpu", "memory", "load"]})

        assert result.success is True
        cpu_entry = next(d for d in result.data if d["name"] == "cpu_usage")
        assert cpu_entry["status"] == "warning"

    @pytest.mark.asyncio
    async def test_snapshot_critical_threshold(self, worker: MonitorWorker) -> None:
        """CPU 96% 应触发 critical"""
        mock_mem = MagicMock()
        mock_mem.percent = 96.0
        mock_mem.used = 15 * 1024**3
        mock_mem.total = 16 * 1024**3

        with (
            patch("src.workers.monitor.psutil.cpu_percent", return_value=96.0),
            patch("src.workers.monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.workers.monitor.psutil.disk_partitions", return_value=[]),
            patch("src.workers.monitor.psutil.getloadavg", return_value=(0.5, 0.5, 0.5)),
            patch("src.workers.monitor.psutil.cpu_count", return_value=4),
        ):
            result = await worker.execute("snapshot", {"include": ["cpu", "memory", "load"]})

        assert result.success is True
        assert "严重告警" in result.message

    # ------------------------------------------------------------------
    # check_port
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_check_port_open(self, worker: MonitorWorker) -> None:
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "src.workers.monitor.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ):
            result = await worker.execute("check_port", {"port": 8080})

        assert result.success is True
        assert result.task_completed is False  # 让 LLM 决定是否继续诊断
        assert isinstance(result.data, dict)
        assert result.data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_port_closed(self, worker: MonitorWorker) -> None:
        with (
            patch(
                "src.workers.monitor.asyncio.open_connection",
                new_callable=AsyncMock,
                side_effect=OSError("Connection refused"),
            ),
            patch(
                "src.workers.monitor.asyncio.wait_for",
                new_callable=AsyncMock,
                side_effect=OSError("Connection refused"),
            ),
        ):
            result = await worker.execute("check_port", {"port": 9999})

        assert result.success is True
        assert result.task_completed is False  # 端口不可达，LLM 应继续诊断
        assert isinstance(result.data, dict)
        assert result.data["status"] == "critical"

    @pytest.mark.asyncio
    async def test_check_port_missing_arg(self, worker: MonitorWorker) -> None:
        result = await worker.execute("check_port", {})
        assert result.success is False
        assert "port" in result.message

    # ------------------------------------------------------------------
    # check_http
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_check_http_ok(self, worker: MonitorWorker) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.workers.monitor.httpx.AsyncClient", return_value=mock_client):
            result = await worker.execute("check_http", {"url": "http://localhost:8080/health"})

        assert result.success is True
        assert result.task_completed is False  # 让 LLM 决定是否继续诊断
        assert isinstance(result.data, dict)
        assert result.data["status_code"] == 200
        assert result.data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_http_server_error(self, worker: MonitorWorker) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.workers.monitor.httpx.AsyncClient", return_value=mock_client):
            result = await worker.execute("check_http", {"url": "http://localhost:8080"})

        assert result.success is True
        assert isinstance(result.data, dict)
        assert result.data["status"] == "critical"

    @pytest.mark.asyncio
    async def test_check_http_missing_arg(self, worker: MonitorWorker) -> None:
        result = await worker.execute("check_http", {})
        assert result.success is False
        assert "url" in result.message

    # ------------------------------------------------------------------
    # check_process
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_check_process_found(self, worker: MonitorWorker) -> None:
        mock_proc = MagicMock()
        mock_proc.info = {
            "name": "python3",
            "pid": 1234,
            "cpu_percent": 5.0,
            "memory_percent": 2.5,
        }

        with patch(
            "src.workers.monitor.psutil.process_iter",
            return_value=[mock_proc],
        ):
            result = await worker.execute("check_process", {"name": "python"})

        assert result.success is True
        assert result.task_completed is False  # 让 LLM 决定是否继续诊断
        assert isinstance(result.data, list)
        assert len(result.data) == 1
        assert result.data[0]["pid"] == 1234
        assert result.data[0]["name"] == "python3"

    @pytest.mark.asyncio
    async def test_check_process_not_found(self, worker: MonitorWorker) -> None:
        with patch(
            "src.workers.monitor.psutil.process_iter",
            return_value=[],
        ):
            result = await worker.execute("check_process", {"name": "nonexistent"})

        assert result.success is True
        assert result.task_completed is False  # 进程未找到，LLM 应继续诊断
        assert result.data is None
        assert "未找到" in result.message

    @pytest.mark.asyncio
    async def test_check_process_missing_arg(self, worker: MonitorWorker) -> None:
        result = await worker.execute("check_process", {})
        assert result.success is False
        assert "name" in result.message

    # ------------------------------------------------------------------
    # top_processes
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_top_processes(self, worker: MonitorWorker) -> None:
        procs = []
        for i, (name, cpu, mem) in enumerate(
            [("python3", 30.0, 5.0), ("node", 50.0, 10.0), ("nginx", 10.0, 2.0)]
        ):
            p = MagicMock()
            p.info = {
                "pid": 1000 + i,
                "name": name,
                "cpu_percent": cpu,
                "memory_percent": mem,
            }
            procs.append(p)

        with patch("src.workers.monitor.psutil.process_iter", return_value=procs):
            result = await worker.execute("top_processes", {"sort_by": "cpu", "limit": 2})

        assert result.success is True
        assert result.task_completed is False  # 让 LLM 决定是否继续分析
        assert isinstance(result.data, list)
        assert len(result.data) == 2
        # node (50%) should be first
        assert result.data[0]["name"] == "node"
        assert result.data[1]["name"] == "python3"

    @pytest.mark.asyncio
    async def test_top_processes_by_memory(self, worker: MonitorWorker) -> None:
        procs = []
        for i, (name, cpu, mem) in enumerate(
            [("python3", 30.0, 15.0), ("node", 50.0, 5.0), ("nginx", 10.0, 20.0)]
        ):
            p = MagicMock()
            p.info = {
                "pid": 1000 + i,
                "name": name,
                "cpu_percent": cpu,
                "memory_percent": mem,
            }
            procs.append(p)

        with patch("src.workers.monitor.psutil.process_iter", return_value=procs):
            result = await worker.execute("top_processes", {"sort_by": "memory", "limit": 10})

        assert result.success is True
        assert isinstance(result.data, list)
        assert len(result.data) == 3
        # nginx (20%) should be first by memory
        assert result.data[0]["name"] == "nginx"
        assert result.data[1]["name"] == "python3"

    @pytest.mark.asyncio
    async def test_top_processes_dry_run(self, worker: MonitorWorker) -> None:
        result = await worker.execute("top_processes", {"dry_run": True})
        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message

    # ------------------------------------------------------------------
    # custom thresholds
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_custom_thresholds(self) -> None:
        """自定义阈值：CPU 50/70 → 55% 应为 warning"""
        custom = {
            "cpu": (50.0, 70.0),
            "memory": (80.0, 95.0),
            "disk": (85.0, 95.0),
        }
        worker = MonitorWorker(thresholds=custom)

        mock_mem = MagicMock()
        mock_mem.percent = 45.0
        mock_mem.used = 4 * 1024**3
        mock_mem.total = 16 * 1024**3

        with (
            patch("src.workers.monitor.psutil.cpu_percent", return_value=55.0),
            patch("src.workers.monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.workers.monitor.psutil.disk_partitions", return_value=[]),
            patch("src.workers.monitor.psutil.getloadavg", return_value=(0.5, 0.5, 0.5)),
            patch("src.workers.monitor.psutil.cpu_count", return_value=4),
        ):
            result = await worker.execute("snapshot", {"include": ["cpu", "memory", "load"]})

        assert result.success is True
        cpu_entry = next(d for d in result.data if d["name"] == "cpu_usage")
        assert cpu_entry["status"] == "warning"

        # memory 45% is below custom threshold 80% → ok
        mem_entry = next(d for d in result.data if d["name"] == "memory_usage")
        assert mem_entry["status"] == "ok"

    @pytest.mark.asyncio
    async def test_custom_thresholds_critical(self) -> None:
        """自定义阈值：CPU 50/70 → 75% 应为 critical"""
        custom = {
            "cpu": (50.0, 70.0),
            "memory": (80.0, 95.0),
            "disk": (85.0, 95.0),
        }
        worker = MonitorWorker(thresholds=custom)

        mock_mem = MagicMock()
        mock_mem.percent = 45.0
        mock_mem.used = 4 * 1024**3
        mock_mem.total = 16 * 1024**3

        with (
            patch("src.workers.monitor.psutil.cpu_percent", return_value=75.0),
            patch("src.workers.monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.workers.monitor.psutil.disk_partitions", return_value=[]),
            patch("src.workers.monitor.psutil.getloadavg", return_value=(0.5, 0.5, 0.5)),
            patch("src.workers.monitor.psutil.cpu_count", return_value=4),
        ):
            result = await worker.execute("snapshot", {"include": ["cpu"]})

        cpu_entry = next(d for d in result.data if d["name"] == "cpu_usage")
        assert cpu_entry["status"] == "critical"

    def test_capabilities_include_top_processes(self, worker: MonitorWorker) -> None:
        caps = worker.get_capabilities()
        assert "top_processes" in caps
