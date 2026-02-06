"""文件操作集成测试

测试用户通过自然语言触发的文件操作工作流。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.workers.system import SystemWorker


class TestFileOperationsWorkflow:
    """文件操作工作流集成测试"""

    @pytest.mark.asyncio
    async def test_create_env_file_workflow(self, tmp_path: Path) -> None:
        """场景：新建一个.env文件并写入TOKEN=xxxx

        模拟用户说"新建一个.env文件写入TOKEN=xxxx"
        Orchestrator 生成 write_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"

        result = await worker.execute(
            "write_file",
            {"path": str(env_file), "content": "TOKEN=xxxx\n"},
        )

        assert result.success is True
        assert env_file.exists()
        assert env_file.read_text() == "TOKEN=xxxx\n"

    @pytest.mark.asyncio
    async def test_replace_env_value_workflow(self, tmp_path: Path) -> None:
        """场景：把.env的TOKEN换成yyyy

        模拟用户说"把.env的TOKEN换成yyyy"
        Orchestrator 生成 replace_in_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=xxxx\nAPI_KEY=zzzz\n")

        result = await worker.execute(
            "replace_in_file",
            {"path": str(env_file), "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"},
        )

        assert result.success is True
        content = env_file.read_text()
        assert "TOKEN=yyyy" in content
        assert "API_KEY=zzzz" in content

    @pytest.mark.asyncio
    async def test_append_env_field_workflow(self, tmp_path: Path) -> None:
        """场景：在.env文件增加API_KEY=zzzz

        模拟用户说"在.env增加API_KEY=zzzz"
        Orchestrator 生成 append_to_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=xxxx\n")

        result = await worker.execute(
            "append_to_file",
            {"path": str(env_file), "content": "API_KEY=zzzz\n"},
        )

        assert result.success is True
        content = env_file.read_text()
        assert "TOKEN=xxxx\n" in content
        assert "API_KEY=zzzz\n" in content

    @pytest.mark.asyncio
    async def test_full_env_management_workflow(self, tmp_path: Path) -> None:
        """完整工作流：创建 → 追加 → 替换

        模拟完整的 .env 文件管理场景：
        1. 创建 .env 并写入 TOKEN=xxxx
        2. 追加 API_KEY=zzzz
        3. 将 TOKEN 的值换成 yyyy
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"

        # Step 1: 创建
        r1 = await worker.execute(
            "write_file",
            {"path": str(env_file), "content": "TOKEN=xxxx\n"},
        )
        assert r1.success is True

        # Step 2: 追加
        r2 = await worker.execute(
            "append_to_file",
            {"path": str(env_file), "content": "API_KEY=zzzz\n"},
        )
        assert r2.success is True

        # Step 3: 替换
        r3 = await worker.execute(
            "replace_in_file",
            {"path": str(env_file), "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"},
        )
        assert r3.success is True

        # 验证最终内容
        final_content = env_file.read_text()
        assert "TOKEN=yyyy" in final_content
        assert "API_KEY=zzzz" in final_content
        assert "TOKEN=xxxx" not in final_content
