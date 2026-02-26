"""TUI 弹窗组件 - 确认弹窗与用户选择弹窗"""

from __future__ import annotations

import contextlib
import json
from typing import Optional

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from src.context.detector import EnvironmentInfo
from src.orchestrator.scenarios import Scenario
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
        self._context_text = context
        self._custom_input_visible = False

    def compose(self) -> ComposeResult:
        with Vertical(id="choice-dialog"):
            yield Static(f"[bold]{self._question}[/bold]", id="choice-title")
            if self._context_text:
                yield Static(self._context_text, id="choice-context")
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


class FirstRunScreen(ModalScreen[Optional[str]]):
    """首次运行引导弹窗"""

    CSS = """
    FirstRunScreen {
        align: center middle;
    }

    #first-run-dialog {
        width: 80%;
        max-width: 90;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
    }

    #first-run-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #first-run-env {
        margin-bottom: 1;
    }

    .first-run-section {
        margin-top: 1;
        color: $text-muted;
    }

    .first-run-button {
        width: 100%;
        margin: 0 0 1 0;
    }

    .first-run-button:focus {
        background: $primary;
    }

    #first-run-skip {
        width: 16;
        margin: 1 auto 0 auto;
    }
    """

    BINDINGS = [
        Binding("escape", "skip", "Skip"),
    ]

    def __init__(
        self,
        env_info: EnvironmentInfo,
        suggestions: list[str],
        scenarios: list[Scenario],
    ) -> None:
        super().__init__()
        self._env_info = env_info
        self._suggestions = suggestions
        self._scenarios = scenarios

    def compose(self) -> ComposeResult:
        with Vertical(id="first-run-dialog"):
            yield Static("🎉 欢迎使用 OpsAI", id="first-run-title")
            yield Static(self._format_env_info(), id="first-run-env")

            yield Static("推荐操作", classes="first-run-section")
            for idx, suggestion in enumerate(self._suggestions, 1):
                yield Button(
                    f"[{idx}] {suggestion}",
                    id=f"first-run-cmd-{idx}",
                    classes="first-run-button",
                )

            if self._scenarios:
                yield Static("推荐场景", classes="first-run-section")
                for scenario in self._scenarios:
                    yield Button(
                        f"{scenario.icon} {scenario.title}",
                        id=f"first-run-scenario-{scenario.id}",
                        classes="first-run-button",
                    )

            yield Button("稍后再说", id="first-run-skip")

    def on_mount(self) -> None:
        buttons = self.query(".first-run-button")
        if buttons:
            buttons.first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("first-run-cmd-"):
            try:
                index = int(button_id.split("-")[-1]) - 1
            except ValueError:
                self.dismiss(None)
                return
            if 0 <= index < len(self._suggestions):
                self.dismiss(self._suggestions[index])
                return

        if button_id.startswith("first-run-scenario-"):
            scenario_id = button_id.replace("first-run-scenario-", "")
            if scenario_id:
                self.dismiss(f"/scenario {scenario_id}")
                return

        self.dismiss(None)

    def action_skip(self) -> None:
        self.dismiss(None)

    def _format_env_info(self) -> str:
        parts = ["检测到你的环境："]

        os_info = f"{self._env_info.os_type} {self._env_info.os_version}"
        parts.append(f"  • 系统: {os_info}")

        if self._env_info.has_docker:
            parts.append(f"  • Docker: {self._env_info.docker_containers} 个运行中")
        else:
            parts.append("  • Docker: 未运行")

        if self._env_info.has_systemd:
            if self._env_info.systemd_services:
                services = ", ".join(self._env_info.systemd_services[:3])
                parts.append(f"  • Systemd: {services}")
            else:
                parts.append("  • Systemd: 可用")

        if self._env_info.has_kubernetes:
            parts.append("  • Kubernetes: 可用")

        if self._env_info.disk_usage > 0:
            parts.append(f"  • 磁盘使用率: {self._env_info.disk_usage:.0f}%")
        if self._env_info.memory_usage > 0:
            parts.append(f"  • 内存使用率: {self._env_info.memory_usage:.0f}%")

        return "\n".join(parts)


class SuggestedCommandScreen(ModalScreen[bool]):
    """建议命令弹窗 — 权限不足时展示 sudo 命令供用户复制"""

    CSS = """
    SuggestedCommandScreen {
        align: center middle;
    }

    #suggest-dialog {
        width: 70%;
        max-width: 80;
        border: heavy $warning;
        padding: 1 2;
        background: $surface;
    }

    #suggest-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #suggest-message {
        margin-bottom: 1;
    }

    #suggest-commands {
        border: heavy $primary;
        padding: 1;
        margin: 1 0;
        background: $panel;
        height: auto;
    }

    #suggest-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #suggest-buttons {
        height: auto;
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("c", "copy_cmd", "Copy"),
        Binding("enter", "close", "Close"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, commands: list[str], message: str) -> None:
        super().__init__()
        self._commands = commands
        self._message = message

    def compose(self) -> ComposeResult:
        cmd_text = "\n".join(self._commands)

        with Vertical(id="suggest-dialog"):
            yield Static("权限不足", id="suggest-title")
            yield Static(self._message, id="suggest-message")
            syntax = Syntax(cmd_text, "bash", theme="ansi_dark", word_wrap=True)
            yield Static(syntax, id="suggest-commands")
            yield Static("快捷键: c 复制命令, Enter/Esc 关闭", id="suggest-hint")
            with Horizontal(id="suggest-buttons"):
                yield Button("复制命令", id="suggest-copy")
                yield Button("关闭", id="suggest-close")

    def on_mount(self) -> None:
        self.query_one("#suggest-close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "suggest-copy":
            self._do_copy()
        else:
            self.dismiss(True)

    def action_copy_cmd(self) -> None:
        self._do_copy()

    def action_close(self) -> None:
        self.dismiss(True)

    def _do_copy(self) -> None:
        text = "\n".join(self._commands)
        with contextlib.suppress(AttributeError, Exception):
            self.app.copy_to_clipboard(text)
        self.dismiss(True)
