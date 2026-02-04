"""AuditWorker 测试"""

from datetime import datetime
from pathlib import Path

import pytest

from src.workers.audit import AuditWorker


class TestAuditWorker:
    """测试 AuditWorker"""

    def test_worker_name(self) -> None:
        """测试 Worker 名称"""
        worker = AuditWorker()
        assert worker.name == "audit"

    def test_capabilities(self) -> None:
        """测试能力列表"""
        worker = AuditWorker()
        caps = worker.get_capabilities()
        assert "log_operation" in caps

    @pytest.mark.asyncio
    async def test_log_operation(self, tmp_path: Path) -> None:
        """测试记录操作"""
        log_path = tmp_path / "audit.log"
        worker = AuditWorker(log_path=log_path)

        result = await worker.execute(
            "log_operation",
            {
                "input": "清理大文件",
                "worker": "system",
                "action": "delete_files",
                "risk": "high",
                "confirmed": "yes",
                "exit_code": 0,
                "output": "Deleted 3 files",
            },
        )

        assert result.success is True
        assert log_path.exists()

        # 验证日志内容
        content = log_path.read_text()
        assert "清理大文件" in content
        assert "system.delete_files" in content
        assert "RISK: high" in content
        assert "CONFIRMED: yes" in content

    @pytest.mark.asyncio
    async def test_log_appends(self, tmp_path: Path) -> None:
        """测试日志追加"""
        log_path = tmp_path / "audit.log"
        worker = AuditWorker(log_path=log_path)

        # 写入两条日志
        await worker.execute(
            "log_operation",
            {"input": "first", "worker": "system", "action": "check", "risk": "safe", "confirmed": "yes", "exit_code": 0, "output": "ok"},
        )
        await worker.execute(
            "log_operation",
            {"input": "second", "worker": "system", "action": "check", "risk": "safe", "confirmed": "yes", "exit_code": 0, "output": "ok"},
        )

        content = log_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert "first" in lines[0]
        assert "second" in lines[1]

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知动作"""
        worker = AuditWorker()
        result = await worker.execute("unknown_action", {})
        assert result.success is False
        assert "Unknown action" in result.message
