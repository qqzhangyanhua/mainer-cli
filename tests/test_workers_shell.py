"""Shell Worker 测试"""

import pytest

from src.workers.shell import (
    MAX_OUTPUT_LENGTH,
    TRUNCATE_HEAD,
    TRUNCATE_TAIL,
    ShellWorker,
)


class TestShellWorker:
    """测试 Shell Worker"""

    def test_worker_name(self) -> None:
        """测试 Worker 名称"""
        worker = ShellWorker()
        assert worker.name == "shell"

    def test_capabilities(self) -> None:
        """测试能力列表"""
        worker = ShellWorker()
        assert worker.get_capabilities() == ["execute_command"]

    @pytest.mark.asyncio
    async def test_execute_command_success(self) -> None:
        """测试执行成功的命令"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo 'Hello World'"},
        )

        assert result.success is True
        # task_completed=False，让 ReAct 循环继续回到 LLM 生成自然语言回答
        assert result.task_completed is False
        assert "Hello World" in result.message

    @pytest.mark.asyncio
    async def test_execute_command_dry_run(self) -> None:
        """测试 dry-run 模式（使用白名单内的命令）"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "ls -la /tmp", "dry_run": True},
        )

        assert result.success is True
        assert result.simulated is True
        assert "[DRY-RUN]" in result.message
        assert "ls -la /tmp" in result.message

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self) -> None:
        """测试危险命令被阻止"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "rm -rf /", "dry_run": True},
        )

        assert result.success is False
        assert "blocked" in result.message.lower()
        assert result.data is not None
        assert result.data.get("blocked") is True

    @pytest.mark.asyncio
    async def test_command_not_in_whitelist_handled_by_analyzer(self) -> None:
        """白名单未匹配的命令由规则引擎处理（未知命令默认 medium，允许执行）"""
        worker = ShellWorker()
        # my-custom-script.sh 不在白名单，规则引擎会判定为 medium 并允许执行
        # 但由于实际文件不存在，命令执行会失败（不是被阻止）
        result = await worker.execute(
            "execute_command",
            {"command": "my-custom-script.sh"},
        )
        # 命令被允许执行（但可能因文件不存在而执行失败）
        # 关键是不再出现 "not in whitelist" 阻止信息
        if result.success is False:
            assert "blocked" not in result.message.lower() or "not in whitelist" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_command_chaining_blocked(self) -> None:
        """测试命令链接被阻止"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "ls && rm -rf /"},
        )

        assert result.success is False
        assert "&&" in result.message or "dangerous" in result.message.lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """测试未知 action"""
        worker = ShellWorker()
        result = await worker.execute("unknown", {})

        assert result.success is False
        assert "Unknown action" in result.message

    @pytest.mark.asyncio
    async def test_execute_command_returns_raw_output(self) -> None:
        """测试返回值包含 raw_output 字段"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo 'test output'"},
        )

        assert result.success is True
        assert result.data is not None
        assert isinstance(result.data, dict)
        assert "raw_output" in result.data
        assert "truncated" in result.data
        assert "test output" in str(result.data["raw_output"])
        assert result.data["truncated"] is False

    def test_truncate_output_short(self) -> None:
        """测试短输出不被截断"""
        worker = ShellWorker()
        short_output = "a" * 100
        result, truncated = worker._truncate_output(short_output)

        assert result == short_output
        assert truncated is False

    def test_truncate_output_exact_limit(self) -> None:
        """测试刚好达到限制的输出不被截断"""
        worker = ShellWorker()
        exact_output = "a" * MAX_OUTPUT_LENGTH
        result, truncated = worker._truncate_output(exact_output)

        assert result == exact_output
        assert truncated is False

    def test_truncate_output_long(self) -> None:
        """测试超长输出被正确截断"""
        worker = ShellWorker()
        long_output = "a" * 10000
        result, truncated = worker._truncate_output(long_output)

        assert truncated is True
        assert len(result) < len(long_output)
        assert "truncated" in result
        # 验证头尾部分被保留
        assert result.startswith("a" * TRUNCATE_HEAD)
        assert result.endswith("a" * TRUNCATE_TAIL)

    @pytest.mark.asyncio
    async def test_grep_no_match_not_error(self) -> None:
        """测试 grep 无匹配时返回成功而非错误（exit code 1 是正常结果）"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "grep 'UNLIKELY_STRING_XYZ_12345' /dev/null"},
        )

        assert result.success is True
        assert result.task_completed is False
        assert "(no matches found)" in result.message

    @pytest.mark.asyncio
    async def test_grep_pipe_no_match_not_error(self) -> None:
        """测试管道中 grep 无匹配时返回成功"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo hello | grep 'UNLIKELY_STRING_XYZ_12345'"},
        )

        assert result.success is True
        assert result.task_completed is False

    @pytest.mark.asyncio
    async def test_grep_with_match_still_success(self) -> None:
        """测试 grep 有匹配时仍然正常返回"""
        worker = ShellWorker()
        result = await worker.execute(
            "execute_command",
            {"command": "echo hello | grep hello"},
        )

        assert result.success is True
        assert "hello" in result.message

    def test_is_exit1_ok_simple_grep(self) -> None:
        """测试 _is_exit1_ok 对简单 grep 命令"""
        assert ShellWorker._is_exit1_ok("grep something file.txt") is True

    def test_is_exit1_ok_pipe_grep(self) -> None:
        """测试 _is_exit1_ok 对管道中的 grep"""
        assert ShellWorker._is_exit1_ok("ps aux | grep nginx | grep -v grep") is True

    def test_is_exit1_ok_non_grep(self) -> None:
        """测试 _is_exit1_ok 对非 grep 命令"""
        assert ShellWorker._is_exit1_ok("ls /nonexistent") is False

    def test_is_exit1_ok_diff(self) -> None:
        """测试 _is_exit1_ok 对 diff 命令"""
        assert ShellWorker._is_exit1_ok("diff file1 file2") is True

    def test_truncate_preserves_head_tail(self) -> None:
        """测试截断保留头尾内容"""
        worker = ShellWorker()
        # 创建有明确头尾的长输出
        head_marker = "HEAD_START_" + "x" * (TRUNCATE_HEAD - 11)
        tail_marker = "y" * (TRUNCATE_TAIL - 9) + "_TAIL_END"
        middle = "m" * 5000
        long_output = head_marker + middle + tail_marker

        result, truncated = worker._truncate_output(long_output)

        assert truncated is True
        assert "HEAD_START_" in result
        assert "_TAIL_END" in result
        # 中间部分应该被截断
        assert "m" * 100 not in result or result.count("m") < 5000
