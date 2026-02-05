"""AnalyzeWorker 单元测试"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.workers.analyze import AnalyzeWorker


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
        return '["echo test"]'


class TestAnalyzeWorker:
    """测试 AnalyzeWorker"""

    def test_worker_name(self) -> None:
        """测试 Worker 名称"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)
        assert worker.name == "analyze"

    def test_capabilities(self) -> None:
        """测试能力列表"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)
        assert worker.get_capabilities() == ["explain"]

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知 action 返回错误"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        result = await worker.execute("unknown_action", {})

        assert result.success is False
        assert "Unknown action" in result.message

    @pytest.mark.asyncio
    async def test_missing_target_returns_error(self) -> None:
        """测试缺少 target 参数时返回错误"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        result = await worker.execute("explain", {})

        assert result.success is False
        assert "请指定" in result.message
        assert result.task_completed is False

    @pytest.mark.asyncio
    async def test_explain_with_successful_commands(self) -> None:
        """测试使用成功命令的分析流程"""
        import tempfile
        from pathlib import Path

        from src.workers.analyze import AnalyzeTemplateCache

        # 模拟 LLM 返回：第一次返回简单命令列表，第二次返回分析总结
        mock_client = MockLLMClient(
            [
                '["echo {name}", "echo info about {name}"]',
                "这是一个测试对象，用于验证分析流程。",
            ]
        )

        # 使用临时缓存，避免被其他测试影响
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            result = await worker.execute(
                "explain",
                {"target": "test-object", "type": "test_type_unique"},
            )

            # 验证结果
            assert result.success is True
            assert result.task_completed is True
            assert "测试" in result.message or "分析" in result.message

    @pytest.mark.asyncio
    async def test_explain_with_empty_type_auto_detects(self) -> None:
        """测试不指定类型时自动检测类型"""
        import tempfile
        from pathlib import Path

        from src.workers.analyze import AnalyzeTemplateCache

        # 模拟 LLM 返回分析总结
        mock_client = MockLLMClient(
            [
                "这是一个测试对象。",
            ]
        )

        # 使用临时缓存
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            # 预设一个可执行的命令到缓存（因为会自动检测为 docker 类型）
            cache.set("docker", ["echo {name}"])

            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            result = await worker.execute(
                "explain",
                {"target": "test-object"},  # 不指定 type，会自动检测为 docker
            )

            assert result.success is True
            assert result.task_completed is True

    def test_parse_command_list_valid_json(self) -> None:
        """测试解析有效的 JSON 命令列表"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        commands = worker._parse_command_list('["cmd1", "cmd2", "cmd3"]')

        assert commands == ["cmd1", "cmd2", "cmd3"]

    def test_parse_command_list_with_markdown(self) -> None:
        """测试解析带 Markdown 代码块的响应"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        response = """```json
["docker inspect {name}", "docker logs {name}"]
```"""
        commands = worker._parse_command_list(response)

        assert commands == ["docker inspect {name}", "docker logs {name}"]

    def test_parse_command_list_invalid_json(self) -> None:
        """测试解析无效 JSON 返回空列表"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        commands = worker._parse_command_list("not valid json")

        assert commands == []

    def test_parse_command_list_filters_non_strings(self) -> None:
        """测试过滤非字符串元素"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        commands = worker._parse_command_list('["cmd1", 123, "cmd2", null]')

        assert commands == ["cmd1", "cmd2"]

    @pytest.mark.asyncio
    async def test_collect_info_replaces_placeholder(self) -> None:
        """测试命令中的占位符被正确替换"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        # 使用简单命令测试占位符替换
        results = await worker._collect_info(
            ["echo {name}"],
            "test-target",
        )

        # 验证命令中的 {name} 被替换为 test-target
        assert "echo test-target" in results
        # 验证输出包含目标名称
        assert "test-target" in results["echo test-target"]

    @pytest.mark.asyncio
    async def test_command_failure_marked_in_results(self) -> None:
        """测试命令执行失败时在结果中标记"""
        mock_client = MagicMock()
        worker = AnalyzeWorker(mock_client)

        # 使用一个肯定会失败的命令
        results = await worker._collect_info(
            ["nonexistent_command_12345"],
            "target",
        )

        # 验证失败被标记
        assert "nonexistent_command_12345" in results
        assert "[Failed:" in results["nonexistent_command_12345"]

    @pytest.mark.asyncio
    async def test_all_commands_fail_returns_error(self) -> None:
        """测试所有命令都失败时返回错误"""
        mock_client = MockLLMClient(
            [
                '["nonexistent_cmd_1", "nonexistent_cmd_2"]',
            ]
        )
        worker = AnalyzeWorker(mock_client)  # type: ignore[arg-type]

        result = await worker.execute(
            "explain",
            {"target": "test", "type": "docker"},
        )

        assert result.success is False
        assert "所有命令执行失败" in result.message

    @pytest.mark.asyncio
    async def test_empty_commands_returns_error(self) -> None:
        """测试 LLM 返回空命令列表时的处理"""
        import tempfile
        from pathlib import Path

        from src.workers.analyze import AnalyzeTemplateCache

        mock_client = MockLLMClient(
            [
                "[]",  # 空命令列表
            ]
        )

        # 使用临时缓存，避免被其他测试影响
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AnalyzeTemplateCache(Path(tmpdir) / "cache.json")
            worker = AnalyzeWorker(mock_client, cache=cache)  # type: ignore[arg-type]

            result = await worker.execute(
                "explain",
                {"target": "test", "type": "unique_test_type"},  # 使用不会被缓存的类型
            )

            assert result.success is False
            assert "无法生成分析步骤" in result.message
