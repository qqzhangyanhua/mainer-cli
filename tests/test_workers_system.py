"""SystemWorker 测试"""

from pathlib import Path

import pytest

from src.workers.system import SystemWorker


class TestSystemWorker:
    """测试 SystemWorker"""

    def test_worker_name(self) -> None:
        """测试 Worker 名称"""
        worker = SystemWorker()
        assert worker.name == "system"

    def test_capabilities(self) -> None:
        """测试能力列表"""
        worker = SystemWorker()
        caps = worker.get_capabilities()
        assert "find_large_files" in caps
        assert "check_disk_usage" in caps
        assert "delete_files" in caps

    @pytest.mark.asyncio
    async def test_check_disk_usage(self) -> None:
        """测试检查磁盘使用"""
        worker = SystemWorker()
        result = await worker.execute("check_disk_usage", {"path": "/"})

        assert result.success is True
        assert result.data is not None
        assert "total" in str(result.data)

    @pytest.mark.asyncio
    async def test_find_large_files(self, tmp_path: Path) -> None:
        """测试查找大文件"""
        # 创建测试文件
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (1024 * 1024 * 2))  # 2MB

        small_file = tmp_path / "small.txt"
        small_file.write_bytes(b"x" * 100)  # 100 bytes

        worker = SystemWorker()
        result = await worker.execute(
            "find_large_files",
            {"path": str(tmp_path), "min_size_mb": 1},
        )

        assert result.success is True
        assert result.data is not None
        # 应该只找到大文件
        files = result.data
        assert isinstance(files, list)
        assert len(files) == 1
        assert "large.txt" in str(files[0])

    @pytest.mark.asyncio
    async def test_find_large_files_empty(self, tmp_path: Path) -> None:
        """测试查找大文件 - 无结果"""
        worker = SystemWorker()
        result = await worker.execute(
            "find_large_files",
            {"path": str(tmp_path), "min_size_mb": 100},
        )

        assert result.success is True
        assert result.data == []

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知动作"""
        worker = SystemWorker()
        result = await worker.execute("unknown_action", {})

        assert result.success is False
        assert "Unknown action" in result.message

    @pytest.mark.asyncio
    async def test_delete_files(self, tmp_path: Path) -> None:
        """测试删除文件"""
        # 创建测试文件
        file1 = tmp_path / "file1.txt"
        file1.write_text("test")
        file2 = tmp_path / "file2.txt"
        file2.write_text("test")

        worker = SystemWorker()
        result = await worker.execute(
            "delete_files",
            {"files": [str(file1), str(file2)]},
        )

        assert result.success is True
        assert not file1.exists()
        assert not file2.exists()

    @pytest.mark.asyncio
    async def test_delete_files_nonexistent(self, tmp_path: Path) -> None:
        """测试删除不存在的文件"""
        worker = SystemWorker()
        result = await worker.execute(
            "delete_files",
            {"files": [str(tmp_path / "nonexistent.txt")]},
        )

        assert result.success is False
        assert "error" in str(result.data)
