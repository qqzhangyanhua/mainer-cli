"""Token 预算管理测试"""

from pathlib import Path

from src.llm.token_budget import TokenBudgetManager


class TestTokenBudgetManager:
    """测试 Token 预算"""

    def test_track_usage_and_warning(self, tmp_path: Path) -> None:
        usage_path = tmp_path / "usage.json"
        manager = TokenBudgetManager(100, 0.8, usage_path)

        status = manager.track_usage(50)
        assert status is not None
        assert status.used == 50
        assert status.warning is False
        assert status.exceeded is False

        status = manager.track_usage(40)
        assert status is not None
        assert status.used == 90
        assert status.warning is True
        assert status.exceeded is False

        status = manager.track_usage(20)
        assert status is not None
        assert status.used == 110
        assert status.exceeded is True
