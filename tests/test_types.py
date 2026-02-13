"""types.py 辅助函数测试"""

from src.types import WorkerResult, get_raw_output, is_output_truncated


class TestGetRawOutput:
    """get_raw_output 辅助函数测试"""

    def test_extracts_raw_output_from_dict_data(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": "hello world", "truncated": False},
        )
        assert get_raw_output(result) == "hello world"

    def test_returns_none_when_data_is_none(self) -> None:
        result = WorkerResult(success=True, message="ok", data=None)
        assert get_raw_output(result) is None

    def test_returns_none_when_data_is_list(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data=[{"name": "file.txt", "type": "file"}],
        )
        assert get_raw_output(result) is None

    def test_returns_none_when_no_raw_output_key(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"command": "ls", "exit_code": 0},
        )
        assert get_raw_output(result) is None

    def test_returns_none_when_raw_output_is_not_string(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": 123},
        )
        assert get_raw_output(result) is None

    def test_returns_empty_string_when_raw_output_is_empty(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": ""},
        )
        # 空字符串仍然是合法的 str，返回空字符串
        assert get_raw_output(result) == ""


class TestIsOutputTruncated:
    """is_output_truncated 辅助函数测试"""

    def test_returns_true_when_truncated(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": "...", "truncated": True},
        )
        assert is_output_truncated(result) is True

    def test_returns_false_when_not_truncated(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": "hello", "truncated": False},
        )
        assert is_output_truncated(result) is False

    def test_returns_false_when_data_is_none(self) -> None:
        result = WorkerResult(success=True, message="ok", data=None)
        assert is_output_truncated(result) is False

    def test_returns_false_when_no_truncated_key(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data={"raw_output": "hello"},
        )
        assert is_output_truncated(result) is False

    def test_returns_false_when_data_is_list(self) -> None:
        result = WorkerResult(
            success=True,
            message="ok",
            data=[{"name": "file.txt", "type": "file"}],
        )
        assert is_output_truncated(result) is False
