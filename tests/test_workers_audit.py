"""AuditWorker 测试"""

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
            {
                "input": "first",
                "worker": "system",
                "action": "check",
                "risk": "safe",
                "confirmed": "yes",
                "exit_code": 0,
                "output": "ok",
            },
        )
        await worker.execute(
            "log_operation",
            {
                "input": "second",
                "worker": "system",
                "action": "check",
                "risk": "safe",
                "confirmed": "yes",
                "exit_code": 0,
                "output": "ok",
            },
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

    @pytest.mark.asyncio
    async def test_dry_run_not_write_log(self, tmp_path: Path) -> None:
        """测试 dry-run 不写日志"""
        log_path = tmp_path / "audit.log"
        worker = AuditWorker(log_path=log_path)

        result = await worker.execute(
            "log_operation",
            {
                "input": "test",
                "worker": "system",
                "action": "check",
                "risk": "safe",
                "confirmed": "yes",
                "exit_code": 0,
                "output": "ok",
                "dry_run": True,
            },
        )

        assert result.success is True
        assert not log_path.exists()

    @pytest.mark.asyncio
    async def test_retention_removes_old_entries(self, tmp_path: Path) -> None:
        """测试保留期会清理旧日志"""
        log_path = tmp_path / "audit.log"
        old_line = (
            "[2000-01-01 00:00:00] INPUT: old | WORKER: system.check | "
            "RISK: safe | CONFIRMED: yes | EXIT: 0 | OUTPUT: ok"
        )
        log_path.write_text(old_line + "\n", encoding="utf-8")

        worker = AuditWorker(log_path=log_path, retain_days=1)
        await worker.execute(
            "log_operation",
            {
                "input": "new",
                "worker": "system",
                "action": "check",
                "risk": "safe",
                "confirmed": "yes",
                "exit_code": 0,
                "output": "ok",
            },
        )

        content = log_path.read_text(encoding="utf-8")
        assert "INPUT: old" not in content
        assert "INPUT: new" in content
