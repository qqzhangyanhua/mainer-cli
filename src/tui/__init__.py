"""OpsAI TUI 入口 - 基于 Textual"""

from __future__ import annotations

from src.tui.app import OpsAIApp


def main() -> None:
    """TUI 入口点"""
    app = OpsAIApp()
    app.run()


__all__ = ["OpsAIApp", "main"]
