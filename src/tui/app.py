"""OpsAI TUI 主应用"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import cast

try:
    import pyperclip

    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.geometry import Offset
from textual.timer import Timer
from textual.widgets import (
    Header,
    Input,
    ListItem,
    ListView,
    LoadingIndicator,
    RichLog,
    Static,
    TextArea,
)

from src import __version__
from src.config.manager import ConfigManager
from src.context.detector import EnvironmentDetector
from src.orchestrator.engine import OrchestratorEngine
from src.orchestrator.scenarios import ScenarioManager
from src.tui.commands import (
    export_history,
    handle_scenario_command,
    show_config,
    show_help,
    show_history_summary,
    show_log_analysis,
)
from src.tui.screens import ConfirmationScreen, SuggestedCommandScreen, UserChoiceScreen
from src.tui.widgets import (
    HistoryWriter,
    SlashCommandSuggester,
    format_path,
    is_subsequence,
    subsequence_gap,
)
from src.types import ConversationEntry, Instruction, RiskLevel


class OpsAIApp(App[str]):
    """OpsAI TUI 应用"""

    TITLE = f"OpsAI Terminal Assistant v{__version__}"
    SELECTION_ENABLED = True

    CSS = """
    Screen {
        layout: vertical;
    }

    #history {
        height: 1fr;
        border: solid green;
        padding: 1;
    }

    #history.hidden {
        display: none;
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

    #loading-container {
        height: auto;
        padding: 0 1;
        display: none;
    }

    #loading-container.visible {
        display: block;
    }

    #loading-container Horizontal {
        height: 1;
        width: 100%;
    }

    #loading-indicator {
        width: 3;
        height: 1;
    }

    #loading-text {
        width: 1fr;
        height: 1;
        color: $text-muted;
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

    #history-copy {
        height: 1fr;
        border: solid $warning;
        padding: 1;
    }

    #history-copy.hidden {
        display: none;
    }

    #copy-mode-banner {
        height: 1;
        background: $warning;
        color: $text;
        text-align: center;
        text-style: bold;
    }

    #copy-mode-banner.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+y", "toggle_copy_mode", "Copy Mode", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config_manager = ConfigManager()
        self._config = self._config_manager.load()
        self._engine = OrchestratorEngine(
            self._config,
            confirmation_callback=self._request_confirmation,
            progress_callback=self._on_progress,
        )

        # 注入回调到 DeployWorker
        deploy_worker = self._engine.get_worker("deploy")
        if deploy_worker is not None:
            if hasattr(deploy_worker, "set_ask_user_callback"):
                deploy_worker.set_ask_user_callback(self._ask_user_choice)
            if hasattr(deploy_worker, "set_confirmation_callback"):
                deploy_worker.set_confirmation_callback(self._deploy_confirmation_adapter)

        self._scenario_manager = ScenarioManager()
        self._current_task: asyncio.Task[None] | None = None
        self._awaiting_confirmation: bool = False
        self._session_history: list[ConversationEntry] = []
        self._last_output: str = ""
        self._status_timer: Timer | None = None
        self._status_enabled: bool = True
        self._status_message: str = ""
        self._verbose_enabled: bool = self._config.tui.show_thinking
        self._slash_menu_items: list[str] = []
        self._slash_menu_visible: bool = False
        self._loading_text: str = "思考中..."
        self._plain_text_buffer: list[str] = []
        self._copy_mode: bool = False
        self._watch_timer: Timer | None = None
        self._watch_alert_manager: object | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="history", wrap=True, highlight=True, markup=True)
        yield TextArea(id="history-copy", read_only=True, classes="hidden")
        yield Static(
            "COPY MODE - select text then Ctrl+C to copy, Ctrl+Y or Escape to exit",
            id="copy-mode-banner",
            classes="hidden",
        )
        with Container(id="loading-container"):
            with Horizontal():
                yield LoadingIndicator(id="loading-indicator")
                yield Static("思考中...", id="loading-text")
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

        self._show_welcome_banner()

        if self._is_first_run():
            self._show_welcome_wizard()

        input_widget.focus()

    def _get_writer(self) -> HistoryWriter:
        """返回 HistoryWriter 代理，所有 write 调用都通过它同步纯文本缓冲"""
        rich_log = self.query_one("#history", RichLog)
        return HistoryWriter(rich_log, self._plain_text_buffer)

    def _is_first_run(self) -> bool:
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        return not marker_file.exists()

    def _mark_first_run_complete(self) -> None:
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.touch()

    def _show_welcome_banner(self) -> None:
        writer = self._get_writer()
        version = __version__
        model = self._config.llm.model
        cwd = str(Path.cwd()).replace(str(Path.home()), "~")

        banner = (
            "[green]   ▄▄▄▄▄▄▄[/green]\n"
            f"[green]   █ ●  ● █[/green]      [bold]OpsAI[/bold] v{version}\n"
            f"[green]   █  ▀▀  █[/green]      [dim]LLM: {model}[/dim]\n"
            f"[green]   ▀▀█▀█▀▀[/green]       [dim]{cwd}[/dim]\n"
            "\n"
            "[bold]Hi! I'm OpsAI, your terminal assistant.[/bold]\n"
            "\n"
            "[dim]Try:[/dim]\n"
            '  [cyan]"查看磁盘使用情况"[/cyan]    [cyan]"列出所有容器"[/cyan]\n'
            '  [cyan]"检查内存占用"[/cyan]        [cyan]"重启 nginx 容器"[/cyan]\n'
            "\n"
            "[dim]Commands: /help /config /clear /history[/dim]\n"
        )
        writer.write(banner)

    def _show_welcome_wizard(self) -> None:
        writer = self._get_writer()
        writer.write("[dim]正在检测环境...[/dim]")
        detector = EnvironmentDetector()
        env_info = detector.detect()
        welcome_msg = detector.generate_welcome_message(env_info)
        writer.clear()
        writer.write(f"[bold green]{welcome_msg}[/bold green]")
        self._mark_first_run_complete()

    # ── 输入事件 ──────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_slash_menu(event.value)

    def on_key(self, event: events.Key) -> None:
        if self._copy_mode:
            if event.key == "escape":
                self._exit_copy_mode()
                event.stop()
            return
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

    def on_resize(self, event: events.Resize) -> None:
        if self._slash_menu_visible:
            self._position_slash_menu(len(self._slash_menu_items))

    # ── 确认与选择弹窗 ──────────────────────────────────

    async def _request_confirmation(self, instruction: Instruction, risk: RiskLevel) -> bool:
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

        self.call_later(
            lambda: self.push_screen(ConfirmationScreen(instruction, risk), _on_dismissed)
        )
        try:
            return await future
        finally:
            self._awaiting_confirmation = False
            input_widget.disabled = False
            input_widget.focus()

    async def _deploy_confirmation_adapter(self, action: str, detail: str) -> bool:
        instruction = Instruction(
            worker="deploy",
            action=action,
            args={"command": detail},
            risk_level="medium",
        )
        return await self._request_confirmation(instruction, "medium")

    async def _ask_user_choice(self, question: str, options: list[str], context: str) -> str:
        input_widget = self.query_one("#user-input", Input)
        input_widget.disabled = True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()

        def _on_dismissed(result: str | None) -> None:
            if not future.done():
                future.set_result(result or "")

        self.call_later(
            lambda: self.push_screen(UserChoiceScreen(question, options, context), _on_dismissed)
        )
        try:
            return await future
        finally:
            input_widget.disabled = False
            input_widget.focus()

    async def _show_suggested_commands(self, commands: list[str], message: str) -> None:
        """弹出建议命令弹窗，供用户复制手动执行"""
        input_widget = self.query_one("#user-input", Input)
        input_widget.disabled = True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _on_dismissed(result: bool | None) -> None:
            if not future.done():
                future.set_result(bool(result))

        self.call_later(
            lambda: self.push_screen(
                SuggestedCommandScreen(commands, message), _on_dismissed
            )
        )
        try:
            await future
        finally:
            input_widget.disabled = False
            input_widget.focus()

    # ── Loading 状态 ──────────────────────────────────────

    def _on_progress(self, step: str, message: str) -> None:
        if step == "result":
            return
        self._update_loading_text(message)
        if self._verbose_enabled:
            step_label = {
                "preprocessing": "[dim][bold]Thinking[/bold][/dim]",
                "reasoning": "[dim][bold]Reasoning[/bold][/dim]",
                "instruction": "[dim][bold]Instruction[/bold][/dim]",
                "safety": "[dim][bold]Safety[/bold][/dim]",
                "approve": "[dim][bold]Approve[/bold][/dim]",
                "executing": "[dim][bold]Executing[/bold][/dim]",
                "error": "[dim][bold]Error[/bold][/dim]",
            }.get(step, f"[dim][bold]{step}[/bold][/dim]")
            writer = self._get_writer()
            writer.write(f"{step_label} {message}")

    def _show_loading(self, text: str = "思考中...") -> None:
        loading_container = self.query_one("#loading-container", Container)
        loading_text = self.query_one("#loading-text", Static)
        loading_text.update(text)
        loading_container.add_class("visible")

    def _hide_loading(self) -> None:
        loading_container = self.query_one("#loading-container", Container)
        loading_container.remove_class("visible")

    def _update_loading_text(self, text: str) -> None:
        loading_text = self.query_one("#loading-text", Static)
        loading_text.update(text)

    # ── 请求执行 ──────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return

        if self._copy_mode:
            return

        writer = self._get_writer()
        input_widget = self.query_one("#user-input", Input)
        input_widget.value = ""
        self._update_slash_menu("")

        if user_input.startswith("/"):
            if self._handle_slash_command(user_input):
                return
            writer.write(f"[yellow]未知命令：{user_input}，输入 /help 查看帮助[/yellow]")
            return

        if self._current_task and not self._current_task.done():
            writer.write("[yellow]已有任务执行中，请等待完成后再输入[/yellow]")
            return

        writer.write(f"[bold cyan]You:[/bold cyan] {user_input}")
        self._show_loading("思考中...")
        self._current_task = asyncio.create_task(self._run_request(user_input))

    async def _run_request(self, user_input: str) -> None:
        writer = self._get_writer()
        try:
            session_id = uuid.uuid4().hex
            result = await self._engine.react_loop_graph(
                user_input,
                session_id=session_id,
                session_history=self._session_history,
            )

            while result == "__APPROVAL_REQUIRED__":
                self._hide_loading()
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

                if approved:
                    self._show_loading("执行中...")

                result = await self._engine.resume_react_loop(
                    session_id,
                    approval_granted=approved,
                    session_history=self._session_history,
                )

            # 处理权限不足建议命令
            if result == "__SUGGESTED_COMMANDS__":
                self._hide_loading()
                state = self._engine.get_graph_state(session_id)
                if state:
                    commands = state.get("suggested_commands", [])
                    final_msg = state.get("final_message", "")
                    if isinstance(commands, list) and commands:
                        await self._show_suggested_commands(commands, final_msg)
                    result = final_msg or "权限不足，请查看建议命令"
                else:
                    result = "权限不足，但状态缺失"

            self._last_output = result
            self._render_result(result)
        except Exception as e:
            writer.write(f"[bold red]Error:[/bold red] {e!s}")
        finally:
            self._hide_loading()
            self._current_task = None

    def _render_result(self, result: str) -> None:
        writer = self._get_writer()
        if "Command:" in result and "Output:" in result:
            lines = result.split("\n")
            writer.write("")
            command_shown = False
            for line in lines:
                if line.startswith("Command:"):
                    if not command_shown:
                        cmd = line.replace("Command: ", "")
                        writer.write(f"[cyan]$ {cmd}[/cyan]")
                        command_shown = True
                elif line.startswith(("Output:", "Error:", "Stderr:", "Exit code:")):
                    continue
                elif line.strip() and not line.startswith("$ "):
                    writer.write(line)
        else:
            writer.write(f"\n[bold green]Assistant:[/bold green] {result}")

    # ── 斜杠命令 ─────────────────────────────────────────

    def _handle_slash_command(self, user_input: str) -> bool:
        self._hide_slash_menu()
        command_line = user_input[1:].strip()
        writer = self._get_writer()
        if not command_line:
            show_help(writer)
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
            show_help(writer)
            return True
        if command == "config":
            new_config = show_config(writer, self._config_manager)
            if new_config is not None:
                self._config = new_config  # type: ignore[assignment]
                self._update_status_bar()
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
            show_history_summary(writer, self._session_history, parts[1:] if len(parts) > 1 else [])
            return True
        if command == "pwd":
            cwd = format_path(Path.cwd())
            writer.write(f"[bold green]当前目录[/bold green] {cwd}")
            return True
        if command == "export":
            export_history(
                parts[1:] if len(parts) > 1 else [],
                writer,
                self._session_history,
                self._config.llm.model,
            )
            return True
        if command in {"scenario", "scenarios"}:
            handle_scenario_command(
                parts[1:] if len(parts) > 1 else [],
                writer,
                self._scenario_manager,
            )
            return True
        if command == "copy":
            self._handle_copy_command(parts[1:] if len(parts) > 1 else [])
            return True
        if command == "monitor":
            sub_args = parts[1:] if len(parts) > 1 else []
            if sub_args and sub_args[0] == "watch":
                self._toggle_watch_mode(sub_args[1:])
            else:
                from src.tui.commands import show_monitor_snapshot

                show_monitor_snapshot(writer)
            return True
        if command in {"logs", "log"}:
            show_log_analysis(
                parts[1:] if len(parts) > 1 else [],
                writer,
            )
            return True
        if command in {"dashboard", "dash"}:
            self._open_dashboard()
            return True

        return False

    def action_clear(self) -> None:
        self._clear_conversation()

    # ── Dashboard 模式 ───────────────────────────────────────

    def _open_dashboard(self) -> None:
        """打开实时健康仪表盘"""
        from src.tui.dashboard import DashboardScreen
        from src.workers.monitor import MonitorWorker

        monitor = self._engine.get_worker("monitor")
        if monitor is None:
            monitor = MonitorWorker()

        thresholds = {
            "cpu": (self._config.monitor.cpu_warning, self._config.monitor.cpu_critical),
            "memory": (self._config.monitor.memory_warning, self._config.monitor.memory_critical),
            "disk": (self._config.monitor.disk_warning, self._config.monitor.disk_critical),
        }

        screen = DashboardScreen(
            monitor_worker=monitor,
            interval=3,
            thresholds=thresholds,
        )
        self.push_screen(screen)

    # ── Watch 模式（持续监控 + 告警）──────────────────────────

    def _toggle_watch_mode(self, args: list[str]) -> None:
        writer = self._get_writer()

        if self._watch_timer is not None:
            # 已在 watch 模式，停止
            self._watch_timer.stop()
            self._watch_timer = None
            self._watch_alert_manager = None
            writer.write("[yellow]Watch 模式已停止[/yellow]")
            return

        # 解析间隔
        interval = self._config.notifications.watch_interval
        for i, arg in enumerate(args):
            if arg == "--interval" and i + 1 < len(args):
                try:
                    interval = int(args[i + 1])
                except ValueError:
                    pass

        # 初始化告警管理器
        from src.workers.notifier import AlertManager

        self._watch_alert_manager = AlertManager(
            duration=self._config.notifications.alert_duration,
            cooldown=self._config.notifications.alert_cooldown,
        )

        # 启动定时器
        self._watch_timer = self.set_interval(
            interval, self._watch_tick, name="watch_timer"
        )
        writer.write(
            f"[green]Watch 模式已启动[/green] (间隔: {interval}s, "
            f"输入 /monitor watch 停止)"
        )
        # 立即执行一次
        self.call_later(self._watch_tick)

    async def _watch_tick(self) -> None:
        """watch 定时回调：采集指标 + 检查告警"""
        import time

        from src.workers.monitor import MonitorWorker
        from src.workers.notifier import AlertManager

        writer = self._get_writer()

        # 获取 MonitorWorker（优先用 engine 中的，否则创建临时实例）
        monitor = self._engine.get_worker("monitor")
        if monitor is None:
            monitor = MonitorWorker()

        result = await monitor.execute("snapshot", {})
        if not result.success or not isinstance(result.data, list):
            return

        # 更新状态栏
        worst = "ok"
        for item in result.data:
            if isinstance(item, dict):
                status = str(item.get("status", "ok"))
                if status == "critical":
                    worst = "critical"
                elif status == "warning" and worst != "critical":
                    worst = "warning"

        status_icon = {"ok": "[green]OK[/green]", "warning": "[yellow]WARN[/yellow]",
                       "critical": "[red]CRIT[/red]"}.get(worst, "")
        self._status_message = f"Watch: {status_icon}"
        self._update_status_bar()

        # 告警检查
        if not isinstance(self._watch_alert_manager, AlertManager):
            return

        alert_mgr: AlertManager = self._watch_alert_manager
        mon_cfg = self._config.monitor
        now = time.monotonic()

        thresholds: dict[str, tuple[float, float]] = {
            "cpu_usage": (mon_cfg.cpu_warning, mon_cfg.cpu_critical),
            "memory_usage": (mon_cfg.memory_warning, mon_cfg.memory_critical),
        }
        # 磁盘分区动态阈值
        for item in result.data:
            if isinstance(item, dict):
                name = str(item.get("name", ""))
                if name.startswith("disk_"):
                    thresholds[name] = (mon_cfg.disk_warning, mon_cfg.disk_critical)

        for item in result.data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if name not in thresholds:
                continue
            try:
                value = float(item.get("value", 0))
            except (ValueError, TypeError):
                continue

            warn_th, crit_th = thresholds[name]
            event = alert_mgr.check_metric(name, value, warn_th, crit_th, now)

            if event is not None:
                # 在 TUI 显示告警
                if event.recovered:
                    writer.write(f"[green][RECOVERED] {event.message}[/green]")
                elif event.severity == "critical":
                    writer.write(f"[red bold][CRITICAL] {event.message}[/red bold]")
                else:
                    writer.write(f"[yellow][WARNING] {event.message}[/yellow]")

                # 发送到通知渠道
                notifier = self._engine.get_worker("notifier")
                if notifier is not None:
                    await notifier.execute("send", {
                        "message": event.message,
                        "severity": event.severity,
                        "title": f"OpsAI: {name}",
                        "recovered": event.recovered,
                    })

    def action_toggle_copy_mode(self) -> None:
        if self._copy_mode:
            self._exit_copy_mode()
        else:
            self._enter_copy_mode()

    def _enter_copy_mode(self) -> None:
        self._copy_mode = True
        rich_log = self.query_one("#history", RichLog)
        copy_area = self.query_one("#history-copy", TextArea)
        banner = self.query_one("#copy-mode-banner", Static)
        input_widget = self.query_one("#user-input", Input)

        rich_log.add_class("hidden")
        copy_area.text = "\n".join(self._plain_text_buffer)
        copy_area.remove_class("hidden")
        banner.remove_class("hidden")
        input_widget.disabled = True
        copy_area.focus()

    def _exit_copy_mode(self) -> None:
        self._copy_mode = False
        rich_log = self.query_one("#history", RichLog)
        copy_area = self.query_one("#history-copy", TextArea)
        banner = self.query_one("#copy-mode-banner", Static)
        input_widget = self.query_one("#user-input", Input)

        copy_area.add_class("hidden")
        banner.add_class("hidden")
        rich_log.remove_class("hidden")
        input_widget.disabled = False
        input_widget.focus()

    def _handle_copy_command(self, args: list[str]) -> None:
        writer = self._get_writer()
        if not args:
            self._do_copy(self._last_output if self._last_output else "")
            if self._last_output:
                writer.write("[dim]已复制最后一条输出到剪贴板[/dim]")
            else:
                writer.write("[yellow]暂无输出可复制[/yellow]")
            return

        sub = args[0].lower()
        if sub == "mode":
            self._enter_copy_mode()
            return
        if sub == "all":
            text = "\n".join(self._plain_text_buffer)
            self._do_copy(text)
            writer.write("[dim]已复制全部历史到剪贴板[/dim]")
            return
        if sub.isdigit():
            n = int(sub)
            recent = self._plain_text_buffer[-n:] if n > 0 else []
            text = "\n".join(recent)
            self._do_copy(text)
            writer.write(f"[dim]已复制最近 {len(recent)} 条到剪贴板[/dim]")
            return

        writer.write("[yellow]用法：/copy [all|N|mode][/yellow]")

    def _do_copy(self, text: str) -> None:
        if not text:
            return
        try:
            self.copy_to_clipboard(text)
        except (AttributeError, Exception):
            if HAS_CLIPBOARD:
                with contextlib.suppress(Exception):
                    pyperclip.copy(text)

    def _clear_conversation(self) -> None:
        writer = self._get_writer()
        writer.clear()
        self._session_history.clear()
        self._last_output = ""
        self._set_status("已清空当前对话")

    # ── 状态栏 ────────────────────────────────────────────

    def _set_status(self, message: str, clear_after: float | None = 2.0) -> None:
        self._status_message = message
        self._update_status_bar()
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        if message and clear_after and clear_after > 0:
            self._status_timer = self.set_timer(clear_after, self._clear_status)

    def _clear_status(self) -> None:
        self._status_message = ""
        self._update_status_bar()
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None

    def _update_status_bar(self) -> None:
        status = self.query_one("#status", Static)
        if not self._status_enabled:
            status.update("")
            status.add_class("hidden")
            return
        status.remove_class("hidden")
        model_name = self._config.llm.model
        cwd = format_path(Path.cwd())
        base = f"模型: {model_name} | 目录: {cwd}"
        if self._status_message:
            status.update(f"{base} | 提示: {self._status_message}")
        else:
            status.update(base)

    def _handle_status_command(self, args: list[str]) -> None:
        writer = self._get_writer()
        if not args:
            self._status_enabled = not self._status_enabled
        else:
            value = args[0].lower()
            if value in {"on", "enable", "1", "true"}:
                self._status_enabled = True
            elif value in {"off", "disable", "0", "false"}:
                self._status_enabled = False
            elif value == "toggle":
                self._status_enabled = not self._status_enabled
            else:
                writer.write("[yellow]用法：/status on|off|toggle[/yellow]")
                return
        self._update_status_bar()
        state = "开启" if self._status_enabled else "关闭"
        self._set_status(f"状态栏已{state}")
        writer.write(f"[dim]状态栏已{state}[/dim]")

    def _handle_verbose_command(self, args: list[str]) -> None:
        writer = self._get_writer()
        if not args:
            self._verbose_enabled = not self._verbose_enabled
        else:
            value = args[0].lower()
            if value in {"on", "enable", "1", "true"}:
                self._verbose_enabled = True
            elif value in {"off", "disable", "0", "false"}:
                self._verbose_enabled = False
            elif value == "toggle":
                self._verbose_enabled = not self._verbose_enabled
            else:
                writer.write("[yellow]用法：/verbose on|off|toggle[/yellow]")
                return

        # 持久化到配置文件
        self._config.tui.show_thinking = self._verbose_enabled
        self._config_manager.save(self._config)

        state = "开启" if self._verbose_enabled else "关闭"
        self._set_status(f"思考过程展示已{state}")
        writer.write(f"[dim]思考过程展示已{state}[/dim]")

    def _handle_theme_command(self, args: list[str]) -> None:
        writer = self._get_writer()
        mode = args[0].lower() if args else "toggle"
        if mode not in {"toggle", "on", "off", "dark", "light"}:
            writer.write("[yellow]用法：/theme toggle|on|off[/yellow]")
            return
        if not hasattr(self, "dark"):
            writer.write("[yellow]当前 Textual 版本不支持主题切换[/yellow]")
            return
        if mode in {"toggle"}:
            self.dark = not self.dark
        elif mode in {"on", "dark"}:
            self.dark = True
        else:
            self.dark = False
        theme_name = "暗色" if self.dark else "亮色"
        self._set_status(f"已切换为{theme_name}主题")
        writer.write(f"[dim]已切换为{theme_name}主题[/dim]")

    # ── 斜杠命令下拉菜单 ─────────────────────────────────

    def _update_slash_menu(self, value: str) -> None:
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
        if not value.startswith("/"):
            return None
        if " " in value:
            return None
        matches = self._match_slash_commands(value)
        if not matches:
            return None
        return matches[0][0]

    def _get_slash_command_specs(self) -> list[tuple[str, str, str]]:
        history_count = len(self._session_history)
        cwd = format_path(Path.cwd())
        model_name = self._config.llm.model
        status_state = "开启" if self._status_enabled else "关闭"
        verbose_state = "开启" if self._verbose_enabled else "关闭"
        theme_state = "未知"
        if hasattr(self, "dark"):
            theme_state = "暗色" if self.dark else "亮色"

        return [
            ("/help", "显示帮助", ""),
            ("/scenario", "查看运维场景（/scenario <id>）", ""),
            ("/clear", "清空当前对话（历史 + 上下文）", ""),
            ("/config", f"显示当前配置（模型: {model_name}）", ""),
            ("/history", f"显示会话历史摘要（当前: {history_count} 条）", ""),
            ("/pwd", f"显示当前目录（{cwd}）", ""),
            ("/export", "导出会话记录（默认导出到当前目录）", ""),
            ("/theme", f"切换主题（当前: {theme_state}）", ""),
            ("/them", "/theme 的别名", ""),
            ("/verbose", f"思考过程展示开关（当前: {verbose_state}）", ""),
            ("/status", f"状态栏开关（当前: {status_state}）", ""),
            ("/copy", "复制输出（/copy all|N|mode）", ""),
            ("/monitor", "系统资源快照（CPU/内存/磁盘/负载）", ""),
            ("/dashboard", "实时健康仪表盘（自动刷新）", ""),
            ("/logs", "日志分析（/logs <容器名> 或 /logs file <路径>）", ""),
            ("/exit", "退出", ""),
        ]

    def _get_slash_commands(self) -> list[str]:
        return [cmd for cmd, _, _ in self._get_slash_command_specs()]

    def _match_slash_commands(self, prefix: str) -> list[tuple[str, str, str]]:
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
                if not is_subsequence(query_plain, target):
                    continue
                score = (1, subsequence_gap(query_plain, target))
            matched.append((score, cmd, desc, marker))

        matched.sort(key=lambda item: (item[0][0], item[0][1], item[1]))
        return [(cmd, desc, marker) for _, cmd, desc, marker in matched]

    def _show_slash_menu(self, commands: list[tuple[str, str, str]]) -> None:
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
            item._command = cmd
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
        menu = self.query_one("#slash-menu", ListView)
        if not self._slash_menu_visible:
            return
        menu.clear()
        menu.add_class("hidden")
        menu.styles.position = "relative"
        self._slash_menu_items = []
        self._slash_menu_visible = False

    def _move_slash_selection(self, delta: int) -> None:
        if not self._slash_menu_items:
            return
        menu = self.query_one("#slash-menu", ListView)
        count = len(self._slash_menu_items)
        current = menu.index if menu.index is not None else 0
        new_index = (current + delta) % count
        menu.index = new_index

    def _accept_slash_selection(self) -> bool:
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
        menu = self.query_one("#slash-menu", ListView)
        input_widget = self.query_one("#user-input", Input)

        screen_size = self.size
        input_region = input_widget.region

        max_items = 6
        border_height = 2
        visible_items = min(item_count, max_items)
        desired_height = visible_items + border_height

        avail_below = screen_size.height - (input_region.y + input_region.height)
        avail_above = input_region.y

        if avail_below < desired_height and avail_above >= desired_height:
            y = max(0, input_region.y - desired_height)
        else:
            if avail_below < desired_height:
                visible_items = max(1, avail_below - border_height)
                desired_height = visible_items + border_height
            y = input_region.y + input_region.height

        if avail_below < desired_height and avail_above > avail_below:
            visible_items = max(1, avail_above - border_height)
            desired_height = visible_items + border_height
            y = max(0, input_region.y - desired_height)

        menu.styles.position = "absolute"
        menu.styles.offset = Offset(input_region.x, y)
        menu.styles.width = input_region.width
        menu.styles.height = desired_height
