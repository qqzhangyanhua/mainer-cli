"""OpsAI TUI 入口 - 基于 Textual"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header, Input, RichLog, Static

from src import __version__
from src.config.manager import ConfigManager
from src.orchestrator.engine import OrchestratorEngine
from src.types import Instruction, RiskLevel


class ConfirmationDialog(Static):
    """确认对话框"""

    def __init__(self, message: str, instruction: Instruction, risk: RiskLevel) -> None:
        super().__init__()
        self.message = message
        self.instruction = instruction
        self.risk = risk
        self._confirmed: bool | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"⚠️  {self.risk.upper()} Risk Operation", classes="dialog-title")
        yield Static(self.message, classes="dialog-message")
        yield Static(
            f"Action: {self.instruction.worker}.{self.instruction.action}",
            classes="dialog-action",
        )
        yield Static("[Y]es / [N]o", classes="dialog-buttons")


class OpsAIApp(App[str]):
    """OpsAI TUI 应用"""

    TITLE = f"OpsAI Terminal Assistant v{__version__}"
    CSS = """
    Screen {
        layout: vertical;
    }

    #history {
        height: 1fr;
        border: solid green;
        padding: 1;
    }

    #input-container {
        height: auto;
        padding: 1;
    }

    #user-input {
        width: 100%;
    }

    .dialog-title {
        text-style: bold;
        color: yellow;
    }

    .dialog-message {
        margin: 1 0;
    }

    .dialog-action {
        color: cyan;
    }

    .dialog-buttons {
        margin-top: 1;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._engine = OrchestratorEngine(
            self._config,
            confirmation_callback=self._request_confirmation,
        )
        self._pending_confirmation: bool | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="history", wrap=True, highlight=True, markup=True)
        yield Container(
            Input(placeholder="Enter your request...", id="user-input"),
            id="input-container",
        )
        yield Footer()

    def _request_confirmation(self, instruction: Instruction, risk: RiskLevel) -> bool:
        """请求用户确认（同步版本，TUI 中需要特殊处理）"""
        # 在 TUI 中，这需要异步处理
        # 暂时返回 True，后续实现完整的确认流程
        return True

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理输入提交"""
        user_input = event.value.strip()
        if not user_input:
            return

        history = self.query_one("#history", RichLog)
        input_widget = self.query_one("#user-input", Input)

        # 清空输入框
        input_widget.value = ""

        # 显示用户输入
        history.write(f"[bold cyan]You:[/bold cyan] {user_input}")
        history.write("[dim]Processing...[/dim]")

        try:
            result = await self._engine.react_loop(user_input)
            history.write(f"[bold green]Assistant:[/bold green] {result}")
        except Exception as e:
            history.write(f"[bold red]Error:[/bold red] {e!s}")

    def action_clear(self) -> None:
        """清空历史"""
        history = self.query_one("#history", RichLog)
        history.clear()


def main() -> None:
    """TUI 入口点"""
    app = OpsAIApp()
    app.run()


if __name__ == "__main__":
    main()
