"""TUI 弹窗组件 - 确认弹窗与用户选择弹窗"""

from __future__ import annotations

import json

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from src.types import Instruction, RiskLevel


class ConfirmationScreen(ModalScreen[bool]):
    """确认弹窗"""

    CSS = """
    ConfirmationScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 70%;
        max-width: 80;
        border: heavy $warning;
        padding: 1 2;
        background: $surface;
    }

    #confirm-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #confirm-message {
        margin-bottom: 1;
    }

    #confirm-action {
        color: $accent;
        margin-bottom: 1;
    }

    #confirm-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #confirm-args {
        border: heavy $primary;
        padding: 1;
        margin: 1 0;
        background: $panel;
        height: auto;
    }

    #confirm-args:focus {
        border: heavy $accent;
    }

    #confirm-buttons {
        height: auto;
        align: center middle;
    }

    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Confirm"),
        Binding("n", "cancel", "Cancel"),
        Binding("escape", "cancel", "Cancel"),
        Binding("a", "toggle_args", "Toggle Args"),
    ]

    def __init__(self, instruction: Instruction, risk: RiskLevel) -> None:
        super().__init__()
        self._instruction = instruction
        self._risk = risk
        self._args_visible = False

    def compose(self) -> ComposeResult:
        title = f"需要确认: {self._risk.upper()} 操作"
        action = f"Action: {self._instruction.worker}.{self._instruction.action}"
        has_args = bool(self._instruction.args)

        with Vertical(id="confirm-dialog"):
            yield Static(title, id="confirm-title")
            yield Static("该操作可能影响系统，请确认是否继续。", id="confirm-message")
            yield Static(action, id="confirm-action")
            yield Static("快捷键：Tab 切换焦点，Enter 确认，Esc 取消", id="confirm-hint")
            if has_args:
                args_json = json.dumps(self._instruction.args, ensure_ascii=False, indent=2)
                syntax = Syntax(args_json, "json", theme="ansi_dark", word_wrap=True)
                yield Static(syntax, id="confirm-args", classes="hidden")
            with Horizontal(id="confirm-buttons"):
                if has_args:
                    yield Button("展开参数", id="toggle-args")
                yield Button("确认", id="confirm-yes")
                yield Button("取消", id="confirm-no")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_toggle_args(self) -> None:
        self._toggle_args()

    def on_mount(self) -> None:
        """默认聚焦确认按钮，支持 Tab 切换"""
        self.query_one("#confirm-yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        elif event.button.id == "toggle-args":
            self._toggle_args()
        else:
            self.dismiss(False)

    def _toggle_args(self) -> None:
        if not self._instruction.args:
            return

        args_widget = self.query_one("#confirm-args", Static)
        toggle_button = self.query_one("#toggle-args", Button)

        self._args_visible = not self._args_visible
        if self._args_visible:
            args_widget.remove_class("hidden")
            toggle_button.label = "收起参数"
        else:
            args_widget.add_class("hidden")
            toggle_button.label = "展开参数"


class UserChoiceScreen(ModalScreen[str]):
    """用户选择弹窗"""

    CSS = """
    UserChoiceScreen {
        align: center middle;
    }

    #choice-dialog {
        width: 70%;
        max-width: 80;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
    }

    #choice-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #choice-context {
        color: $text-muted;
        margin-bottom: 1;
    }

    #choice-options {
        height: auto;
        margin: 1 0;
    }

    .choice-button {
        width: 100%;
        margin: 0 0 1 0;
    }

    .choice-button:focus {
        background: $primary;
    }

    #choice-custom-input {
        width: 100%;
        margin: 1 0;
    }

    #choice-custom-input.hidden {
        display: none;
    }

    #choice-hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_1", "Option 1", show=False),
        Binding("2", "select_2", "Option 2", show=False),
        Binding("3", "select_3", "Option 3", show=False),
        Binding("4", "select_4", "Option 4", show=False),
    ]

    def __init__(self, question: str, options: list[str], context: str) -> None:
        super().__init__()
        self._question = question
        self._options = options
        self._context = context
        self._custom_input_visible = False

    def compose(self) -> ComposeResult:
        with Vertical(id="choice-dialog"):
            yield Static(f"[bold]{self._question}[/bold]", id="choice-title")
            if self._context:
                yield Static(self._context, id="choice-context")
            with Vertical(id="choice-options"):
                for i, option in enumerate(self._options, 1):
                    btn_id = f"choice-btn-{i}"
                    label = f"[{i}] {option}"
                    if i == 1:
                        label += " (推荐)"
                    yield Button(label, id=btn_id, classes="choice-button")
            yield Input(placeholder="输入自定义值...", id="choice-custom-input", classes="hidden")
            yield Static("快捷键: 数字键选择，Esc 取消", id="choice-hint")

    def on_mount(self) -> None:
        """默认聚焦第一个按钮"""
        buttons = self.query(".choice-button")
        if buttons:
            buttons.first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("choice-btn-"):
            try:
                index = int(btn_id.split("-")[-1]) - 1
                if 0 <= index < len(self._options):
                    selected = self._options[index]
                    if selected.lower() in ("自定义", "custom", "其他", "other"):
                        self._show_custom_input()
                    else:
                        self.dismiss(selected)
            except ValueError:
                pass

    def _show_custom_input(self) -> None:
        """显示自定义输入框"""
        custom_input = self.query_one("#choice-custom-input", Input)
        custom_input.remove_class("hidden")
        custom_input.focus()
        self._custom_input_visible = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理自定义输入提交"""
        if event.input.id == "choice-custom-input":
            value = event.value.strip()
            if value:
                self.dismiss(value)

    def action_cancel(self) -> None:
        """取消选择，返回空字符串"""
        self.dismiss("")

    def action_select_1(self) -> None:
        self._select_by_index(0)

    def action_select_2(self) -> None:
        self._select_by_index(1)

    def action_select_3(self) -> None:
        self._select_by_index(2)

    def action_select_4(self) -> None:
        self._select_by_index(3)

    def _select_by_index(self, index: int) -> None:
        """通过索引选择选项"""
        if 0 <= index < len(self._options):
            selected = self._options[index]
            if selected.lower() in ("自定义", "custom", "其他", "other"):
                self._show_custom_input()
            else:
                self.dismiss(selected)
