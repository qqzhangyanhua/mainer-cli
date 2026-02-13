"""path_utils 路径规范化工具测试"""

import os

from src.workers.path_utils import normalize_path


class TestNormalizePath:
    """normalize_path 测试"""

    def test_none_uses_default(self) -> None:
        result = normalize_path(None)
        assert result == os.path.abspath(".")

    def test_none_with_custom_default(self) -> None:
        result = normalize_path(None, default="/")
        assert result == "/"

    def test_dot_resolves_to_cwd(self) -> None:
        result = normalize_path(".")
        assert result == os.path.abspath(".")

    def test_tilde_expands(self) -> None:
        result = normalize_path("~/test")
        assert result == os.path.abspath(os.path.expanduser("~/test"))

    def test_relative_path_becomes_absolute(self) -> None:
        result = normalize_path("foo/bar")
        assert os.path.isabs(result)
        assert result.endswith("foo/bar")

    def test_absolute_path_unchanged(self) -> None:
        result = normalize_path("/tmp/test")
        assert result == "/tmp/test"

    def test_slash_default(self) -> None:
        result = normalize_path(None, default="/")
        assert result == "/"
