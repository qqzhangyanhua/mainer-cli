"""TUI 测试"""

import pytest

from src.tui import OpsAIApp


class TestTUI:
    """测试 TUI"""

    @pytest.mark.asyncio
    async def test_app_startup(self) -> None:
        """测试应用启动"""
        app = OpsAIApp()
        async with app.run_test() as pilot:
            # 验证标题
            assert "OpsAI" in app.title

    @pytest.mark.asyncio
    async def test_input_widget_exists(self) -> None:
        """测试输入框存在"""
        app = OpsAIApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user-input")
            assert input_widget is not None

    @pytest.mark.asyncio
    async def test_history_widget_exists(self) -> None:
        """测试历史区域存在"""
        app = OpsAIApp()
        async with app.run_test() as pilot:
            history = app.query_one("#history")
            assert history is not None
