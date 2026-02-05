"""OpsAI TUI 入口 - 基于 Textual"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, cast

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Header, Input, ListItem, ListView, RichLog, Static
from rich.syntax import Syntax
from textual import events
from textual.suggester import Suggester
from textual.geometry import Offset

from src import __version__
from src.config.manager import ConfigManager
from src.context.detector import EnvironmentDetector
from src.orchestrator.engine import OrchestratorEngine
from src.orchestrator.scenarios import ScenarioManager
from src.types import ConversationEntry, Instruction, RiskLevel


class SlashCommandSuggester(Suggester):
    """斜杠命令的幽灵文本提示"""

    def __init__(self, suggestion_provider: Callable[[str], str | None]) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._suggestion_provider = suggestion_provider

    async def get_suggestion(self, value: str) -> str | None:
        return self._suggestion_provider(value)


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
                yield Static(syntax, id="confirm-args", classes="hidden", can_focus=False)
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
            args_widget.can_focus = True
            toggle_button.label = "收起参数"
            args_widget.focus()
        else:
            args_widget.add_class("hidden")
            args_widget.can_focus = False
            toggle_button.label = "展开参数"


class OpsAIApp(App[str]):
    """OpsAI TUI 应用"""

    TITLE = f"OpsAI Terminal Assistant v{__version__}"
    SELECTION_ENABLED = True  # 启用文本选择
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

    #status {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }

    #status.hidden {
        display: none;
    }

    #slash-menu {
        height: auto;
        max-height: 10;
        border: round $primary;
        padding: 0;
        background: $panel;
        opacity: 0.98;
        overlay: screen;
        scrollbar-size-vertical: 1;
    }

    #slash-menu.hidden {
        display: none;
    }

    #slash-menu > ListItem {
        height: auto;
        max-height: 1;
        min-height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
        margin: 0;
        content-align: left middle;
    }

    #slash-menu > ListItem:hover {
        background: $boost;
    }

    #slash-menu > ListItem.-highlight {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    #slash-menu ListItem > Horizontal {
        height: 1;
        width: 100%;
        align: left middle;
    }

    #slash-menu .slash-cmd {
        width: 12;
        height: 1;
        color: $text;
        text-style: bold;
        content-align: left middle;
    }

    #slash-menu .slash-desc {
        width: 1fr;
        height: 1;
        color: $text-muted;
        content-align: left middle;
    }

    #slash-menu .slash-tag {
        width: 3;
        height: 1;
        color: $warning;
        content-align: right middle;
    }

    #user-input {
        width: 100%;
    }

    Input .input--suggestion {
        color: #777777;
        text-style: dim;
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
        Binding("ctrl+y", "copy_last", "Copy Last", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._engine = OrchestratorEngine(
            self._config,
            confirmation_callback=self._request_confirmation,
            progress_callback=self._on_progress,
            use_langgraph=True,
        )
        self._scenario_manager = ScenarioManager()
        self._current_task: asyncio.Task | None = None
        self._awaiting_confirmation: bool = False
        # 会话级对话历史 - 跨轮次保持
        self._session_history: list[ConversationEntry] = []
        # 最后一次输出，用于复制
        self._last_output: str = ""
        # 状态栏自动清理定时器
        self._status_timer: Timer | None = None
        # 状态栏开关
        self._status_enabled: bool = True
        # 状态栏提示消息
        self._status_message: str = ""
        # 详细日志开关
        self._verbose_enabled: bool = True
        # 斜杠命令下拉提示
        self._slash_menu_items: list[str] = []
        self._slash_menu_visible: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="history", wrap=True, highlight=True, markup=True)
        yield Container(
            Input(placeholder="Enter your request...", id="user-input"),
            id="input-container",
        )
        yield ListView(id="slash-menu", classes="hidden")
        yield Static("", id="status")

    def on_mount(self) -> None:
        """初始化状态栏和首次运行检查"""
        self._update_status_bar()
        input_widget = self.query_one("#user-input", Input)
        input_widget.suggester = SlashCommandSuggester(self._get_slash_suggestion)

        # 检查是否首次运行
        if self._is_first_run():
            self._show_welcome_wizard()

    def _is_first_run(self) -> bool:
        """检查是否首次运行

        Returns:
            如果首次运行返回 True
        """
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        return not marker_file.exists()

    def _mark_first_run_complete(self) -> None:
        """标记首次运行已完成"""
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.touch()

    def _show_welcome_wizard(self) -> None:
        """显示欢迎向导"""
        history = self.query_one("#history", RichLog)

        # 显示加载提示
        history.write("[dim]正在检测环境...[/dim]")

        # 检测环境
        detector = EnvironmentDetector()
        env_info = detector.detect()

        # 生成并显示欢迎消息
        welcome_msg = detector.generate_welcome_message(env_info)
        history.clear()  # 清除加载提示
        history.write(f"[bold green]{welcome_msg}[/bold green]")

        # 标记首次运行完成
        self._mark_first_run_complete()

    def on_input_changed(self, event: Input.Changed) -> None:
        """输入变更时更新命令提示"""
        self._update_slash_menu(event.value)

    def on_key(self, event: events.Key) -> None:
        """下拉提示键盘交互"""
        if not self._slash_menu_visible:
            return

        input_widget = self.query_one("#user-input", Input)
        if not input_widget.has_focus:
            return

        if event.key in {"down", "up"}:
            delta = 1 if event.key == "down" else -1
            self._move_slash_selection(delta)
            event.stop()
            return

        if event.key in {"enter", "tab"}:
            if self._accept_slash_selection():
                event.stop()
            return

        if event.key == "escape":
            self._hide_slash_menu()
            event.stop()
            return

    def on_resize(self, event: events.Resize) -> None:
        """窗口大小变化时重新定位下拉菜单"""
        if self._slash_menu_visible:
            self._position_slash_menu(len(self._slash_menu_items))

    async def _request_confirmation(self, instruction: Instruction, risk: RiskLevel) -> bool:
        """请求用户确认（异步弹窗）"""
        if self._awaiting_confirmation:
            return False

        self._awaiting_confirmation = True

        input_widget = self.query_one("#user-input", Input)
        input_widget.disabled = True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _on_dismissed(result: bool | None) -> None:
            if not future.done():
                future.set_result(bool(result))

        self.push_screen(ConfirmationScreen(instruction, risk), _on_dismissed)

        try:
            return await future
        finally:
            self._awaiting_confirmation = False
            input_widget.disabled = False
            input_widget.focus()

    def _on_progress(self, step: str, message: str) -> None:
        """进度回调：实时显示执行步骤"""
        history = self.query_one("#history", RichLog)

        # 只显示过程信息，不显示最终结果（避免重复）
        if step == "result":
            # 只显示执行状态（✅/❌），不显示完整输出
            if message.startswith("✅") or message.startswith("❌"):
                status_line = message.split("\n")[0]  # 只取第一行状态
                history.write(f"[dim]{status_line}[/dim]")
            return

        if not self._verbose_enabled:
            return

        # 其他步骤正常显示
        history.write(f"[dim]{message}[/dim]")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理输入提交"""
        user_input = event.value.strip()
        if not user_input:
            return

        history = self.query_one("#history", RichLog)
        input_widget = self.query_one("#user-input", Input)

        # 清空输入框
        input_widget.value = ""
        self._update_slash_menu("")

        # 处理 TUI 斜杠命令
        if user_input.startswith("/"):
            if self._handle_slash_command(user_input):
                return
            history.write(f"[yellow]未知命令：{user_input}，输入 /help 查看帮助[/yellow]")
            return

        # 有任务执行中时阻止并发请求
        if self._current_task and not self._current_task.done():
            history.write("[yellow]已有任务执行中，请等待完成后再输入[/yellow]")
            return

        # 显示用户输入
        history.write(f"[bold cyan]You:[/bold cyan] {user_input}")

        # 异步执行请求，避免阻塞 UI
        self._current_task = asyncio.create_task(self._run_request(user_input))

    async def _run_request(self, user_input: str) -> None:
        """执行请求（后台任务）"""
        history = self.query_one("#history", RichLog)
        try:
            session_id = uuid.uuid4().hex
            result = await self._engine.react_loop_graph(
                user_input,
                session_id=session_id,
                session_history=self._session_history,
            )

            while result == "__APPROVAL_REQUIRED__":
                state = self._engine.get_graph_state(session_id)
                if not state:
                    result = "错误：需要审批但状态缺失"
                    break

                inst_dict = state.get("current_instruction")
                if not isinstance(inst_dict, dict):
                    result = "错误：需要审批但指令缺失"
                    break

                instruction = Instruction(
                    worker=str(inst_dict.get("worker", "")),
                    action=str(inst_dict.get("action", "")),
                    args=inst_dict.get("args", {}),  # type: ignore[arg-type]
                    risk_level=inst_dict.get("risk_level", "medium"),  # type: ignore[arg-type]
                    dry_run=bool(inst_dict.get("dry_run", False)),
                )

                risk = state.get("risk_level", "medium")
                if risk not in ("safe", "medium", "high"):
                    risk = "medium"
                risk_level = cast(RiskLevel, risk)

                approved = await self._request_confirmation(instruction, risk_level)
                result = await self._engine.resume_react_loop(
                    session_id,
                    approval_granted=approved,
                    session_history=self._session_history,
                )

            # 保存原始输出用于复制
            self._last_output = result

            # 渲染结果
            self._render_result(result)
        except Exception as e:
            history.write(f"[bold red]Error:[/bold red] {e!s}")
        finally:
            self._current_task = None

    def _render_result(self, result: str) -> None:
        """渲染结果输出"""
        history = self.query_one("#history", RichLog)

        # 如果结果包含命令输出，格式化显示
        if "Command:" in result and "Output:" in result:
            lines = result.split("\n")
            history.write("")  # 空行分隔

            # 标记是否已显示命令
            command_shown = False

            for line in lines:
                if line.startswith("Command:"):
                    # 只显示一次命令行
                    if not command_shown:
                        cmd = line.replace("Command: ", "")
                        history.write(f"[cyan]$ {cmd}[/cyan]")
                        command_shown = True
                elif line.startswith("Output:"):
                    continue  # 跳过 "Output:" 标题
                elif line.startswith("Error:"):
                    continue  # Error 信息会单独处理
                elif line.startswith("Exit code:"):
                    continue  # 跳过退出码
                elif line.strip() and not line.startswith("$ "):  # 非空行且不是重复的命令
                    history.write(line)
        else:
            # 非命令输出，直接显示（如聊天回复、分析结果等）
            history.write(f"\n[bold green]Assistant:[/bold green] {result}")

    def action_clear(self) -> None:
        """清空历史"""
        self._clear_conversation()

    def action_copy_last(self) -> None:
        """复制最后一次输出到剪贴板"""
        history = self.query_one("#history", RichLog)
        
        if not HAS_CLIPBOARD:
            history.write("[yellow]💡 Clipboard feature not available.[/yellow]")
            history.write("[dim]   Install with: pip install opsai[clipboard][/dim]")
            return
        
        if self._last_output:
            try:
                pyperclip.copy(self._last_output)
                history.write("[dim]✓ Copied to clipboard[/dim]")
            except Exception as e:
                history.write(f"[red]Failed to copy: {e}[/red]")

    def _handle_slash_command(self, user_input: str) -> bool:
        """处理 TUI 斜杠命令，返回是否已处理"""
        self._hide_slash_menu()
        command_line = user_input[1:].strip()
        if not command_line:
            self._show_help()
            return True

        parts = command_line.split()
        command = parts[0].lower()

        if command == "clear":
            self._clear_conversation()
            return True
        if command == "exit":
            self.exit()
            return True
        if command == "help":
            self._show_help()
            return True
        if command == "config":
            self._show_config()
            return True
        if command == "status":
            self._handle_status_command(parts[1:] if len(parts) > 1 else [])
            return True
        if command in {"them", "theme"}:
            self._handle_theme_command(parts[1:] if len(parts) > 1 else [])
            return True
        if command == "verbose":
            self._handle_verbose_command(parts[1:] if len(parts) > 1 else [])
            return True
        if command == "history":
            self._show_history()
            return True
        if command == "pwd":
            self._show_pwd()
            return True
        if command == "export":
            self._export_history(parts[1:] if len(parts) > 1 else [])
            return True
        if command in {"scenario", "scenarios"}:
            self._handle_scenario_command(parts[1:] if len(parts) > 1 else [])
            return True

        return False

    def _clear_conversation(self) -> None:
        """清空当前对话（历史 + 上下文）"""
        history = self.query_one("#history", RichLog)
        history.clear()
        self._session_history.clear()
        self._last_output = ""
        self._set_status("已清空当前对话")

    def _show_help(self) -> None:
        """展示帮助信息"""
        history = self.query_one("#history", RichLog)
        history.write("[bold green]可用命令[/bold green]")
        history.write("/help     - 显示帮助")
        history.write("/scenario - 查看运维场景（/scenario <id>）")
        history.write("/clear    - 清空当前对话（历史 + 上下文）")
        history.write("/config   - 显示当前配置（敏感字段已脱敏）")
        history.write("/history  - 显示会话历史摘要")
        history.write("/pwd      - 显示当前目录")
        history.write("/export   - 导出会话记录（/export [json|md] [path]）")
        history.write("/theme    - 切换主题（/theme toggle|on|off）")
        history.write("/verbose  - 详细日志开关（/verbose on|off|toggle）")
        history.write("/status   - 状态栏开关（/status on|off|toggle）")
        history.write("/exit     - 退出")
        history.write("[dim]快捷键：Ctrl+C 退出，Ctrl+L 清空对话[/dim]")

    def _show_config(self) -> None:
        """展示当前配置（敏感字段脱敏）"""
        history = self.query_one("#history", RichLog)
        try:
            config = self._config_manager.load()
        except Exception as e:
            history.write(f"[red]读取配置失败：{e!s}[/red]")
            return

        self._config = config

        config_dict = config.model_dump()
        config_dict["llm"]["api_key"] = self._mask_secret(config_dict["llm"].get("api_key", ""))
        config_dict["http"]["github_token"] = self._mask_secret(
            config_dict["http"].get("github_token", "")
        )

        config_json = json.dumps(config_dict, ensure_ascii=False, indent=2)
        config_path = self._config_manager.get_config_path()

        history.write(f"[bold green]当前配置[/bold green]（{config_path}）")
        history.write(Syntax(config_json, "json", theme="ansi_dark", word_wrap=True))
        history.write("[dim]提示：敏感字段已脱敏显示[/dim]")
        self._update_status_bar()

    @staticmethod
    def _mask_secret(value: str) -> str:
        """敏感信息脱敏显示"""
        if not value:
            return ""
        if len(value) <= 4:
            return "*" * len(value)
        return "*" * (len(value) - 4) + value[-4:]

    def _set_status(self, message: str, clear_after: float | None = 2.0) -> None:
        """更新状态栏提示，可选自动清理"""
        self._status_message = message
        self._update_status_bar()

        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None

        if message and clear_after and clear_after > 0:
            self._status_timer = self.set_timer(clear_after, self._clear_status)

    def _clear_status(self) -> None:
        """清空状态栏"""
        self._status_message = ""
        self._update_status_bar()
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None

    def _handle_status_command(self, args: list[str]) -> None:
        """处理状态栏开关命令"""
        history = self.query_one("#history", RichLog)
        if not args:
            self._status_enabled = not self._status_enabled
            self._update_status_bar()
            return

        value = args[0].lower()
        if value in {"on", "enable", "1", "true"}:
            self._status_enabled = True
        elif value in {"off", "disable", "0", "false"}:
            self._status_enabled = False
        elif value == "toggle":
            self._status_enabled = not self._status_enabled
        else:
            history.write("[yellow]用法：/status on|off|toggle[/yellow]")
            return

        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """刷新状态栏显示"""
        status = self.query_one("#status", Static)

        if not self._status_enabled:
            status.update("")
            status.add_class("hidden")
            return

        status.remove_class("hidden")
        model_name = self._config.llm.model
        cwd = self._format_path(Path.cwd())
        base = f"模型: {model_name} | 目录: {cwd}"

        if self._status_message:
            status.update(f"{base} | 提示: {self._status_message}")
        else:
            status.update(base)

    @staticmethod
    def _format_path(path: Path) -> str:
        """格式化路径为短路径（优先 ~）"""
        try:
            home = Path.home()
            if path == home:
                return "~"
            if home in path.parents:
                return f"~/{path.relative_to(home)}"
        except Exception:
            return str(path)
        return str(path)

    def _update_slash_menu(self, value: str) -> None:
        """根据输入更新斜杠命令下拉提示"""
        if not value.startswith("/"):
            self._hide_slash_menu()
            return

        if " " in value:
            self._hide_slash_menu()
            return

        prefix = value.strip()
        commands = self._get_slash_commands()
        if prefix in commands and prefix != "/":
            self._hide_slash_menu()
            return

        matched = self._match_slash_commands(prefix)
        if not matched:
            self._hide_slash_menu()
            return

        self._show_slash_menu(matched)

    def _get_slash_suggestion(self, value: str) -> str | None:
        """获取幽灵文本建议"""
        if not value.startswith("/"):
            return None
        if " " in value:
            return None
        matches = self._match_slash_commands(value)
        if not matches:
            return None
        return matches[0][0]

    def _get_slash_command_specs(self) -> list[tuple[str, str, str]]:
        """获取斜杠命令与描述（含动态信息与标记）"""
        history_count = len(self._session_history)
        cwd = self._format_path(Path.cwd())
        model_name = self._config.llm.model
        status_state = "开启" if self._status_enabled else "关闭"
        verbose_state = "开启" if self._verbose_enabled else "关闭"
        theme_state = "未知"
        if hasattr(self, "dark"):
            theme_state = "暗色" if self.dark else "亮色"

        return [
            ("/help", "显示帮助", ""),
            ("/scenario", "查看运维场景（/scenario <id>）", "📋"),
            ("/clear", "清空当前对话（历史 + 上下文）", "⚠"),
            ("/config", f"显示当前配置（模型: {model_name}）", ""),
            ("/history", f"显示会话历史摘要（当前: {history_count} 条）", ""),
            ("/pwd", f"显示当前目录（{cwd}）", ""),
            ("/export", "导出会话记录（默认导出到当前目录）", "⬇"),
            ("/theme", f"切换主题（当前: {theme_state}）", "🎨"),
            ("/them", "/theme 的别名", ""),
            ("/verbose", f"详细日志开关（当前: {verbose_state}）", ""),
            ("/status", f"状态栏开关（当前: {status_state}）", ""),
            ("/exit", "退出", "⏻"),
        ]

    def _get_slash_commands(self) -> list[str]:
        """获取全部斜杠命令列表"""
        return [cmd for cmd, _, _ in self._get_slash_command_specs()]

    def _match_slash_commands(self, prefix: str) -> list[tuple[str, str, str]]:
        """按前缀/模糊匹配命令"""
        specs = self._get_slash_command_specs()
        if prefix == "/":
            return specs

        query = prefix.lower()
        query_plain = query[1:] if query.startswith("/") else query
        matched: list[tuple[tuple[int, int], str, str, str]] = []

        for cmd, desc, marker in specs:
            cmd_lower = cmd.lower()
            if cmd_lower.startswith(query):
                score = (0, len(cmd_lower))
            else:
                target = cmd_lower.lstrip("/")
                if not self._is_subsequence(query_plain, target):
                    continue
                score = (1, self._subsequence_gap(query_plain, target))
            matched.append((score, cmd, desc, marker))

        matched.sort(key=lambda item: (item[0][0], item[0][1], item[1]))
        return [(cmd, desc, marker) for _, cmd, desc, marker in matched]

    @staticmethod
    def _is_subsequence(needle: str, haystack: str) -> bool:
        """判断 needle 是否为 haystack 的子序列"""
        index = 0
        for ch in needle:
            index = haystack.find(ch, index)
            if index == -1:
                return False
            index += 1
        return True

    @staticmethod
    def _subsequence_gap(needle: str, haystack: str) -> int:
        """子序列匹配的间隔评分（越小越好）"""
        index = -1
        gaps = 0
        for ch in needle:
            next_index = haystack.find(ch, index + 1)
            if next_index == -1:
                return 10_000
            gaps += next_index - index - 1
            index = next_index
        return gaps

    def _show_slash_menu(self, commands: list[tuple[str, str, str]]) -> None:
        """显示下拉命令列表"""
        menu = self.query_one("#slash-menu", ListView)
        menu.clear()

        items: list[ListItem] = []
        command_names: list[str] = []
        for cmd, desc, marker in commands:
            row = Horizontal(
                Static(cmd, classes="slash-cmd"),
                Static(desc, classes="slash-desc"),
                Static(marker, classes="slash-tag"),
            )
            item = ListItem(row)
            setattr(item, "_command", cmd)
            items.append(item)
            command_names.append(cmd)

        menu.extend(items)
        menu.remove_class("hidden")
        self._slash_menu_items = command_names
        self._slash_menu_visible = True
        self._position_slash_menu(len(command_names))
        if command_names:
            menu.index = 0

    def _hide_slash_menu(self) -> None:
        """隐藏下拉命令列表"""
        menu = self.query_one("#slash-menu", ListView)
        if not self._slash_menu_visible:
            return
        menu.clear()
        menu.add_class("hidden")
        menu.styles.position = "relative"
        self._slash_menu_items = []
        self._slash_menu_visible = False

    def _move_slash_selection(self, delta: int) -> None:
        """移动下拉选中项"""
        if not self._slash_menu_items:
            return
        menu = self.query_one("#slash-menu", ListView)
        count = len(self._slash_menu_items)
        current = menu.index if menu.index is not None else 0
        new_index = (current + delta) % count
        menu.index = new_index

    def _accept_slash_selection(self) -> bool:
        """应用当前选中命令到输入框"""
        if not self._slash_menu_items:
            return False

        menu = self.query_one("#slash-menu", ListView)
        index = menu.index if menu.index is not None else 0
        if index < 0 or index >= len(self._slash_menu_items):
            return False

        command = self._slash_menu_items[index]
        input_widget = self.query_one("#user-input", Input)
        input_widget.value = command
        input_widget.cursor_position = len(command)
        input_widget.focus()
        self._hide_slash_menu()
        return True

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """点击下拉项时应用命令"""
        if event.list_view.id != "slash-menu":
            return
        command = getattr(event.item, "_command", "")
        if command:
            input_widget = self.query_one("#user-input", Input)
            input_widget.value = command
            input_widget.cursor_position = len(command)
            input_widget.focus()
            self._hide_slash_menu()

    def _position_slash_menu(self, item_count: int) -> None:
        """根据空间位置调整下拉菜单位置，避免被底部遮挡"""
        menu = self.query_one("#slash-menu", ListView)
        input_widget = self.query_one("#user-input", Input)

        screen_size = self.size
        input_region = input_widget.region

        max_items = 6
        border_height = 2  # 上下边框
        visible_items = min(item_count, max_items)
        desired_height = visible_items + border_height

        avail_below = screen_size.height - (input_region.y + input_region.height)
        avail_above = input_region.y

        if avail_below < desired_height and avail_above >= desired_height:
            # 放到输入框上方
            y = max(0, input_region.y - desired_height)
        else:
            # 默认放到输入框下方
            if avail_below < desired_height:
                # 空间不足时压缩高度
                visible_items = max(1, avail_below - border_height)
                desired_height = visible_items + border_height
            y = input_region.y + input_region.height

        if avail_below < desired_height and avail_above > avail_below:
            # 上方空间更大，放上方并压缩高度
            visible_items = max(1, avail_above - border_height)
            desired_height = visible_items + border_height
            y = max(0, input_region.y - desired_height)

        menu.styles.position = "absolute"
        menu.styles.offset = Offset(input_region.x, y)
        menu.styles.width = input_region.width
        menu.styles.height = desired_height

    def _handle_verbose_command(self, args: list[str]) -> None:
        """处理详细日志开关命令"""
        history = self.query_one("#history", RichLog)
        if not args:
            self._verbose_enabled = not self._verbose_enabled
            state = "开启" if self._verbose_enabled else "关闭"
            self._set_status(f"详细日志已{state}")
            history.write(f"[dim]详细日志已{state}[/dim]")
            return

        value = args[0].lower()
        if value in {"on", "enable", "1", "true"}:
            self._verbose_enabled = True
        elif value in {"off", "disable", "0", "false"}:
            self._verbose_enabled = False
        elif value == "toggle":
            self._verbose_enabled = not self._verbose_enabled
        else:
            history.write("[yellow]用法：/verbose on|off|toggle[/yellow]")
            return

        state = "开启" if self._verbose_enabled else "关闭"
        self._set_status(f"详细日志已{state}")
        history.write(f"[dim]详细日志已{state}[/dim]")

    def _handle_theme_command(self, args: list[str]) -> None:
        """处理主题切换命令"""
        history = self.query_one("#history", RichLog)
        mode = args[0].lower() if args else "toggle"
        if mode not in {"toggle", "on", "off", "dark", "light"}:
            history.write("[yellow]用法：/theme toggle|on|off[/yellow]")
            return

        if not hasattr(self, "dark"):
            history.write("[yellow]当前 Textual 版本不支持主题切换[/yellow]")
            return

        if mode in {"toggle"}:
            self.dark = not self.dark
        elif mode in {"on", "dark"}:
            self.dark = True
        else:
            self.dark = False

        theme_name = "暗色" if self.dark else "亮色"
        self._set_status(f"已切换为{theme_name}主题")
        history.write(f"[dim]已切换为{theme_name}主题[/dim]")

    def _show_history(self) -> None:
        """显示会话历史摘要"""
        history = self.query_one("#history", RichLog)
        total = len(self._session_history)
        if total == 0:
            history.write("[dim]暂无会话历史[/dim]")
            return

        history.write(f"[bold green]会话历史[/bold green] 共 {total} 条")
        recent = self._session_history[-3:]
        start_index = total - len(recent) + 1
        for offset, entry in enumerate(recent):
            index = start_index + offset
            user_text = self._truncate_text(entry.user_input or "", 60)
            result_text = self._truncate_text(entry.result.message, 60)
            history.write(f"{index}. 用户: {user_text}")
            history.write(f"[dim]   结果: {result_text}[/dim]")

    def _show_pwd(self) -> None:
        """显示当前目录"""
        history = self.query_one("#history", RichLog)
        cwd = self._format_path(Path.cwd())
        history.write(f"[bold green]当前目录[/bold green] {cwd}")

    def _handle_scenario_command(self, args: list[str]) -> None:
        """处理场景命令

        用法：
            /scenario         - 列出所有场景
            /scenario <id>    - 查看场景详情并执行
            /scenario search <keyword> - 搜索场景
        """
        history = self.query_one("#history", RichLog)

        if not args:
            # 显示所有场景
            self._show_scenarios()
            return

        first_arg = args[0].lower()

        if first_arg == "search" and len(args) > 1:
            # 搜索场景
            keyword = " ".join(args[1:])
            results = self._scenario_manager.search(keyword)
            if results:
                history.write(f"[bold green]搜索结果：{keyword}[/bold green]")
                for s in results:
                    history.write(f"  {s.icon} [{s.id}] {s.title}")
                    history.write(f"      {s.description}")
            else:
                history.write(f"[yellow]未找到匹配的场景：{keyword}[/yellow]")
            return

        # 查找场景
        scenario = self._scenario_manager.get_by_id(first_arg)
        if not scenario:
            # 尝试模糊匹配
            results = self._scenario_manager.search(first_arg)
            if results:
                history.write(f"[yellow]未找到场景 '{first_arg}'，你是否想要：[/yellow]")
                for s in results[:3]:
                    history.write(f"  {s.icon} [{s.id}] {s.title}")
            else:
                history.write(f"[yellow]未找到场景：{first_arg}[/yellow]")
                history.write("[dim]输入 /scenario 查看所有可用场景[/dim]")
            return

        # 显示场景详情
        risk_badge = {
            "safe": "[green][安全][/green]",
            "medium": "[yellow][中等风险][/yellow]",
            "high": "[red][高危][/red]",
        }.get(scenario.risk_level, "")

        history.write(f"[bold green]{scenario.icon} {scenario.title}[/bold green] {risk_badge}")
        history.write(f"[dim]{scenario.description}[/dim]")
        history.write("")
        history.write("[bold]执行步骤：[/bold]")
        for i, step in enumerate(scenario.steps, 1):
            history.write(f"  {i}. {step.description}")
            history.write(f"     [cyan]> {step.prompt}[/cyan]")
        history.write("")
        history.write("[dim]提示：输入上述命令或直接描述你的需求[/dim]")

    def _show_scenarios(self) -> None:
        """显示所有场景列表"""
        history = self.query_one("#history", RichLog)

        # 按分类组织
        categories = {
            "troubleshooting": "🔴 故障排查",
            "maintenance": "🛠️  日常维护",
            "deployment": "🚀 项目部署",
            "monitoring": "📊 监控查看",
        }

        history.write("[bold green]═══ 常见运维场景 ═══[/bold green]")

        for cat_id, cat_name in categories.items():
            cat_scenarios = self._scenario_manager.get_by_category(cat_id)
            if not cat_scenarios:
                continue

            history.write(f"\n[bold]{cat_name}[/bold]")
            for scenario in cat_scenarios:
                risk_badge = {
                    "safe": "[green]🟢[/green]",
                    "medium": "[yellow]🟡[/yellow]",
                    "high": "[red]🔴[/red]",
                }.get(scenario.risk_level, "")

                history.write(f"  {scenario.icon} [{scenario.id}] {scenario.title} {risk_badge}")
                history.write(f"      [dim]{scenario.description}[/dim]")

        history.write("")
        history.write("[dim]💡 使用方法：[/dim]")
        history.write("[dim]   - 输入 /scenario <ID> 查看详情（如 '/scenario disk_full'）[/dim]")
        history.write("[dim]   - 或直接描述你的问题（如 '服务打不开'）[/dim]")

    def _export_history(self, args: list[str]) -> None:
        """导出会话记录"""
        history = self.query_one("#history", RichLog)

        export_format = "json"
        export_path: Path | None = None

        if args:
            first = args[0].lower()
            if first in {"json", "md", "markdown"}:
                export_format = "md" if first in {"md", "markdown"} else "json"
                if len(args) > 1:
                    export_path = Path(args[1]).expanduser()
            else:
                export_path = Path(args[0]).expanduser()
                if export_path.suffix.lower() == ".md":
                    export_format = "md"
                else:
                    export_format = "json"

        if export_path is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"opsai-history-{timestamp}.{export_format}"
            export_path = Path.cwd() / filename

        export_data = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "version": __version__,
            "model": self._config.llm.model,
            "cwd": str(Path.cwd()),
            "entries": [entry.model_dump() for entry in self._session_history],
        }

        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            if export_format == "md":
                content = self._render_history_markdown(export_data)
                export_path.write_text(content, encoding="utf-8")
            else:
                export_path.write_text(
                    json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except Exception as e:
            history.write(f"[red]导出失败：{e!s}[/red]")
            return

        history.write(f"[green]已导出会话记录：{self._format_path(export_path)}[/green]")

    def _render_history_markdown(self, export_data: dict[str, object]) -> str:
        """渲染 Markdown 导出内容"""
        lines: list[str] = []
        lines.append("# OpsAI 会话导出")
        lines.append("")
        lines.append(f"- 导出时间: {export_data.get('exported_at')}")
        lines.append(f"- 版本: {export_data.get('version')}")
        lines.append(f"- 模型: {export_data.get('model')}")
        lines.append(f"- 目录: {export_data.get('cwd')}")
        lines.append("")

        entries = export_data.get("entries", [])
        if isinstance(entries, list) and entries:
            for index, entry in enumerate(entries, start=1):
                lines.append(f"## 记录 {index}")
                user_input = ""
                instruction = ""
                result_message = ""
                if isinstance(entry, dict):
                    user_input = str(entry.get("user_input") or "")
                    instruction_obj = entry.get("instruction") or {}
                    if isinstance(instruction_obj, dict):
                        worker = instruction_obj.get("worker", "")
                        action = instruction_obj.get("action", "")
                        args = instruction_obj.get("args", {})
                        instruction = f"{worker}.{action} {args}"
                    result_obj = entry.get("result") or {}
                    if isinstance(result_obj, dict):
                        result_message = str(result_obj.get("message", ""))
                lines.append(f"- 用户输入: {user_input}")
                lines.append(f"- 指令: {instruction}")
                lines.append(f"- 结果: {result_message}")
                lines.append("")
        else:
            lines.append("暂无会话记录")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        """截断文本用于摘要显示"""
        text = text.strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1]}…"


def main() -> None:
    """TUI 入口点"""
    app = OpsAIApp()
    app.run()


if __name__ == "__main__":
    main()
