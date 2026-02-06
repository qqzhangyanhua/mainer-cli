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

    @pytest.mark.asyncio
    async def test_delete_files_with_path_fallback(self, tmp_path: Path) -> None:
        """测试 delete_files 兼容 path 参数"""
        worker = SystemWorker()
        target = tmp_path / "to_delete.txt"
        target.write_text("bye")

        # LLM 可能传 path 而不是 files
        result = await worker.execute(
            "delete_files",
            {"path": str(target)},
        )

        assert result.success is True
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_delete_files_string_instead_of_list(self, tmp_path: Path) -> None:
        """测试 delete_files 兼容字符串参数"""
        worker = SystemWorker()
        target = tmp_path / "to_delete.txt"
        target.write_text("bye")

        # LLM 可能传 string 而不是 list
        result = await worker.execute(
            "delete_files",
            {"files": str(target)},
        )

        assert result.success is True
        assert not target.exists()

    # === write_file 测试 ===

    @pytest.mark.asyncio
    async def test_write_file_creates_new_file(self, tmp_path: Path) -> None:
        """测试创建新文件"""
        worker = SystemWorker()
        target = tmp_path / "test.env"

        result = await worker.execute(
            "write_file",
            {"path": str(target), "content": "TOKEN=xxxx"},
        )

        assert result.success is True
        assert result.task_completed is True
        assert target.exists()
        assert target.read_text() == "TOKEN=xxxx"

    @pytest.mark.asyncio
    async def test_write_file_overwrites_existing(self, tmp_path: Path) -> None:
        """测试覆写已有文件"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("OLD_CONTENT")

        result = await worker.execute(
            "write_file",
            {"path": str(target), "content": "NEW_CONTENT"},
        )

        assert result.success is True
        assert target.read_text() == "NEW_CONTENT"

    @pytest.mark.asyncio
    async def test_write_file_dry_run(self, tmp_path: Path) -> None:
        """测试 write_file dry-run 模式"""
        worker = SystemWorker()
        target = tmp_path / "test.env"

        result = await worker.execute(
            "write_file",
            {"path": str(target), "content": "TOKEN=xxxx", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "10 chars" in result.message
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_write_file_parent_not_exists(self, tmp_path: Path) -> None:
        """测试父目录不存在"""
        worker = SystemWorker()
        target = tmp_path / "nonexistent" / "test.env"

        result = await worker.execute(
            "write_file",
            {"path": str(target), "content": "TOKEN=xxxx"},
        )

        assert result.success is False
        assert "Parent directory does not exist" in result.message

    @pytest.mark.asyncio
    async def test_write_file_path_is_directory(self, tmp_path: Path) -> None:
        """测试路径是目录"""
        worker = SystemWorker()

        result = await worker.execute(
            "write_file",
            {"path": str(tmp_path), "content": "TOKEN=xxxx"},
        )

        assert result.success is False
        assert "Path is a directory" in result.message

    # === append_to_file 测试 ===

    @pytest.mark.asyncio
    async def test_append_to_file_success(self, tmp_path: Path) -> None:
        """测试追加内容"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=xxxx")

        result = await worker.execute(
            "append_to_file",
            {"path": str(target), "content": "\nAPI_KEY=zzzz"},
        )

        assert result.success is True
        assert result.task_completed is True
        assert target.read_text() == "TOKEN=xxxx\nAPI_KEY=zzzz"

    @pytest.mark.asyncio
    async def test_append_to_file_dry_run(self, tmp_path: Path) -> None:
        """测试 append_to_file dry-run 模式"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=xxxx")

        result = await worker.execute(
            "append_to_file",
            {"path": str(target), "content": "\nAPI_KEY=zzzz", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert target.read_text() == "TOKEN=xxxx"

    @pytest.mark.asyncio
    async def test_append_to_file_not_exists(self, tmp_path: Path) -> None:
        """测试追加到不存在的文件"""
        worker = SystemWorker()
        target = tmp_path / "nonexistent.env"

        result = await worker.execute(
            "append_to_file",
            {"path": str(target), "content": "API_KEY=zzzz"},
        )

        assert result.success is False
        assert "File not found" in result.message

    # === replace_in_file 测试 ===

    @pytest.mark.asyncio
    async def test_replace_in_file_exact_match(self, tmp_path: Path) -> None:
        """测试精确匹配替换"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=old_value\nAPI_KEY=keep")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "TOKEN=old_value", "new": "TOKEN=new_value"},
        )

        assert result.success is True
        assert result.task_completed is True
        content = target.read_text()
        assert "TOKEN=new_value" in content
        assert "API_KEY=keep" in content

    @pytest.mark.asyncio
    async def test_replace_in_file_multiple_matches(self, tmp_path: Path) -> None:
        """测试多处匹配全部替换"""
        worker = SystemWorker()
        target = tmp_path / "config.txt"
        target.write_text("host=localhost\ndb_host=localhost\nredis_host=localhost")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "localhost", "new": "192.168.1.100"},
        )

        assert result.success is True
        content = target.read_text()
        assert content.count("192.168.1.100") == 3
        assert "localhost" not in content

    @pytest.mark.asyncio
    async def test_replace_in_file_with_count(self, tmp_path: Path) -> None:
        """测试限定替换次数"""
        worker = SystemWorker()
        target = tmp_path / "config.txt"
        target.write_text("AAA\nAAA\nAAA")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "AAA", "new": "BBB", "count": 2},
        )

        assert result.success is True
        content = target.read_text()
        assert content.count("BBB") == 2
        assert content.count("AAA") == 1

    @pytest.mark.asyncio
    async def test_replace_in_file_regex(self, tmp_path: Path) -> None:
        """测试正则表达式替换"""
        worker = SystemWorker()
        target = tmp_path / "config.txt"
        target.write_text("PORT=8080\nPORT=3000\nPORT=5432")

        result = await worker.execute(
            "replace_in_file",
            {
                "path": str(target),
                "old": r"PORT=\d+",
                "new": "PORT=9999",
                "regex": True,
            },
        )

        assert result.success is True
        content = target.read_text()
        assert content == "PORT=9999\nPORT=9999\nPORT=9999"

    @pytest.mark.asyncio
    async def test_replace_in_file_no_match(self, tmp_path: Path) -> None:
        """测试无匹配情况"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=xxxx")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "NONEXISTENT", "new": "REPLACEMENT"},
        )

        assert result.success is True
        assert "No matches found" in result.message
        assert target.read_text() == "TOKEN=xxxx"

    @pytest.mark.asyncio
    async def test_replace_in_file_invalid_regex(self, tmp_path: Path) -> None:
        """测试无效正则表达式"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=xxxx")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "[invalid", "new": "replacement", "regex": True},
        )

        assert result.success is False
        assert "Invalid regex pattern" in result.message

    @pytest.mark.asyncio
    async def test_replace_in_file_dry_run(self, tmp_path: Path) -> None:
        """测试 replace_in_file dry-run 模式"""
        worker = SystemWorker()
        target = tmp_path / "test.env"
        target.write_text("TOKEN=old\nTOKEN=old")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "TOKEN=old", "new": "TOKEN=new", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "Matches found: 2" in result.message
        assert target.read_text() == "TOKEN=old\nTOKEN=old"

    @pytest.mark.asyncio
    async def test_replace_in_file_file_not_found(self, tmp_path: Path) -> None:
        """测试替换不存在的文件"""
        worker = SystemWorker()
        target = tmp_path / "nonexistent.env"

        result = await worker.execute(
            "replace_in_file",
            {"path": str(target), "old": "TOKEN", "new": "KEY"},
        )

        assert result.success is False
        assert "File not found" in result.message
