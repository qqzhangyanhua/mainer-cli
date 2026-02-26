"""命令缓存测试"""

from src.orchestrator.command_cache import CommandCache


class TestCommandCache:
    """测试命令缓存"""

    def test_container_list_all(self) -> None:
        cache = CommandCache()
        match = cache.match("查看所有容器")
        assert match is not None
        assert match.instruction.worker == "container"
        assert match.instruction.action == "list_containers"
        assert match.instruction.args.get("all") is True

    def test_disk_usage(self) -> None:
        cache = CommandCache()
        match = cache.match("检查磁盘使用情况")
        assert match is not None
        assert match.instruction.worker == "system"
        assert match.instruction.action == "check_disk_usage"
        assert match.instruction.args.get("path") == "/"

    def test_check_port(self) -> None:
        cache = CommandCache()
        match = cache.match("检查8080端口是否开放")
        assert match is not None
        assert match.instruction.worker == "monitor"
        assert match.instruction.action == "check_port"
        assert match.instruction.args.get("port") == 8080

    def test_no_match(self) -> None:
        cache = CommandCache()
        assert cache.match("帮我优化数据库") is None
