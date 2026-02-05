"""分析模板缓存测试"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.workers.analyze import AnalyzeTemplate, AnalyzeTemplateCache


class TestAnalyzeTemplateCache:
    """测试分析模板缓存"""

    def test_get_nonexistent_returns_none(self) -> None:
        """测试获取不存在的缓存返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            result = cache.get("nonexistent")

            assert result is None

    def test_set_and_get(self) -> None:
        """测试设置并获取缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            commands = ["docker inspect {name}", "docker logs {name}"]
            cache.set("docker", commands)

            result = cache.get("docker")

            assert result == commands

    def test_hit_count_increment(self) -> None:
        """测试命中计数递增"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["cmd1"])

            # 第一次获取
            cache.get("docker")
            # 第二次获取
            cache.get("docker")
            # 第三次获取
            cache.get("docker")

            templates = cache.list_all()
            assert templates["docker"].hit_count == 3

    def test_clear_specific(self) -> None:
        """测试清除指定类型缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["cmd1"])
            cache.set("process", ["cmd2"])

            count = cache.clear("docker")

            assert count == 1
            assert cache.get("docker") is None
            assert cache.get("process") == ["cmd2"]

    def test_clear_nonexistent_returns_zero(self) -> None:
        """测试清除不存在的类型返回 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            count = cache.clear("nonexistent")

            assert count == 0

    def test_clear_all(self) -> None:
        """测试清除所有缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["cmd1"])
            cache.set("process", ["cmd2"])
            cache.set("port", ["cmd3"])

            count = cache.clear()

            assert count == 3
            assert cache.list_all() == {}

    def test_persistence(self) -> None:
        """测试缓存持久化到文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"

            # 第一个缓存实例写入
            cache1 = AnalyzeTemplateCache(cache_path)
            cache1.set("docker", ["docker inspect {name}"])

            # 第二个缓存实例读取
            cache2 = AnalyzeTemplateCache(cache_path)
            result = cache2.get("docker")

            assert result == ["docker inspect {name}"]

    def test_corrupted_file_handled(self) -> None:
        """测试损坏的缓存文件不阻塞"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"

            # 写入损坏的 JSON
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w") as f:
                f.write("not valid json {{{")

            # 缓存应该正常初始化，忽略损坏的文件
            cache = AnalyzeTemplateCache(cache_path)
            result = cache.get("docker")

            assert result is None
            assert cache.list_all() == {}

    def test_list_all(self) -> None:
        """测试列出所有模板"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["cmd1", "cmd2"])
            cache.set("process", ["cmd3"])

            templates = cache.list_all()

            assert len(templates) == 2
            assert "docker" in templates
            assert "process" in templates
            assert templates["docker"].commands == ["cmd1", "cmd2"]

    def test_exists(self) -> None:
        """测试检查模板是否存在"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["cmd1"])

            assert cache.exists("docker") is True
            assert cache.exists("nonexistent") is False

    def test_overwrite_existing(self) -> None:
        """测试覆盖已存在的模板"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = AnalyzeTemplateCache(cache_path)

            cache.set("docker", ["old_cmd"])
            cache.get("docker")  # 增加 hit_count
            cache.get("docker")

            # 覆盖
            cache.set("docker", ["new_cmd1", "new_cmd2"])

            result = cache.get("docker")
            templates = cache.list_all()

            assert result == ["new_cmd1", "new_cmd2"]
            # 覆盖后 hit_count 从 0 开始，get 一次后变为 1
            assert templates["docker"].hit_count == 1


class TestAnalyzeTemplate:
    """测试 AnalyzeTemplate 模型"""

    def test_create_template(self) -> None:
        """测试创建模板"""
        template = AnalyzeTemplate(
            commands=["cmd1", "cmd2"],
            created_at="2026-02-04T10:00:00",
            hit_count=5,
        )

        assert template.commands == ["cmd1", "cmd2"]
        assert template.created_at == "2026-02-04T10:00:00"
        assert template.hit_count == 5

    def test_default_hit_count(self) -> None:
        """测试默认 hit_count 为 0"""
        template = AnalyzeTemplate(
            commands=["cmd1"],
            created_at="2026-02-04T10:00:00",
        )

        assert template.hit_count == 0
