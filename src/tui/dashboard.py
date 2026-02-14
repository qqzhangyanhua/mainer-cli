"""健康仪表盘 Screen — 实时系统监控面板"""

from __future__ import annotations

from typing import Optional

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, ProgressBar, Static

from src.types import MonitorMetric


class MetricBar(Static):
    """单个指标可视化条"""

    def __init__(
        self,
        label: str,
        value: float = 0.0,
        unit: str = "%",
        warn_at: float = 80.0,
        crit_at: float = 95.0,
        bar_id: str = "",
    ) -> None:
        super().__init__(id=bar_id)
        self._label = label
        self._value = value
        self._unit = unit
        self._warn_at = warn_at
        self._crit_at = crit_at

    def set_value(self, value: float) -> None:
        self._value = value
        self._render_bar()

    def _render_bar(self) -> None:
        val = self._value
        # 颜色选择
        if val >= self._crit_at:
            color = "red bold"
            icon = "[!]"
        elif val >= self._warn_at:
            color = "yellow"
            icon = "[~]"
        else:
            color = "green"
            icon = "[+]"

        # 进度条绘制
        bar_width = 30
        filled = int(val / 100 * bar_width) if val <= 100 else bar_width
        empty = bar_width - filled

        bar_char = "#"
        bar = f"[{color}]{bar_char * filled}[/]{'.' * empty}"
        label = f"{self._label:>10}"
        value_str = f"{val:6.1f}{self._unit}"

        self.update(f" {icon} {label} {bar} {value_str}")

    def on_mount(self) -> None:
        self._render_bar()


class DashboardScreen(Screen[None]):
    """实时系统健康仪表盘"""

    CSS = """
    DashboardScreen {
        background: $surface;
    }

    #dashboard-container {
        padding: 1 2;
    }

    #metrics-panel {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: heavy $primary;
    }

    #metrics-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #disk-panel {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: heavy $accent;
    }

    #disk-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #info-panel {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: heavy $secondary;
    }

    #info-title {
        text-style: bold;
        color: $secondary;
    }

    #status-line {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 2;
    }

    MetricBar {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit_dashboard", "Exit Dashboard"),
        Binding("escape", "quit_dashboard", "Exit Dashboard"),
        Binding("r", "refresh", "Refresh Now"),
    ]

    def __init__(
        self,
        monitor_worker: object,
        interval: int = 3,
        thresholds: Optional[dict[str, tuple[float, float]]] = None,
    ) -> None:
        super().__init__()
        self._monitor_worker = monitor_worker
        self._interval = interval
        self._thresholds = thresholds or {
            "cpu": (80.0, 95.0),
            "memory": (80.0, 95.0),
            "disk": (85.0, 95.0),
        }
        self._refresh_timer: Optional[Timer] = None
        self._tick_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="dashboard-container"):
            # 系统指标面板
            with Vertical(id="metrics-panel"):
                yield Static("System Metrics", id="metrics-title")
                cpu_warn, cpu_crit = self._thresholds.get("cpu", (80.0, 95.0))
                mem_warn, mem_crit = self._thresholds.get("memory", (80.0, 95.0))
                yield MetricBar(
                    "CPU", warn_at=cpu_warn, crit_at=cpu_crit, bar_id="bar-cpu"
                )
                yield MetricBar(
                    "Memory", warn_at=mem_warn, crit_at=mem_crit, bar_id="bar-memory"
                )

            # 磁盘面板
            with Vertical(id="disk-panel"):
                yield Static("Disk Usage", id="disk-title")
                disk_warn, disk_crit = self._thresholds.get("disk", (85.0, 95.0))
                yield MetricBar(
                    "Disk /", warn_at=disk_warn, crit_at=disk_crit, bar_id="bar-disk"
                )

            # 信息面板
            with Vertical(id="info-panel"):
                yield Static("System Info", id="info-title")
                yield Static("Loading...", id="info-content")

            # 状态栏
            yield Static(
                f"Auto-refresh: {self._interval}s | Press 'r' to refresh, 'q' to exit",
                id="status-line",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(self._interval, self._tick)
        # 立即刷新一次
        self.call_after_refresh(self._do_refresh)

    def action_quit_dashboard(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.stop()
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self.call_after_refresh(self._do_refresh)

    async def _tick(self) -> None:
        self._tick_count += 1
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        """采集并更新指标"""
        try:
            from src.workers.monitor import MonitorWorker

            if not isinstance(self._monitor_worker, MonitorWorker):
                return

            result = await self._monitor_worker.execute("snapshot", {})
            if not result.success or not result.data:
                return

            data = result.data
            if not isinstance(data, dict):
                return

            # 更新 CPU
            cpu_val = data.get("cpu_percent")
            if isinstance(cpu_val, (int, float)):
                self.query_one("#bar-cpu", MetricBar).set_value(float(cpu_val))

            # 更新 Memory
            mem_val = data.get("memory_percent")
            if isinstance(mem_val, (int, float)):
                self.query_one("#bar-memory", MetricBar).set_value(float(mem_val))

            # 更新 Disk
            disk_val = data.get("disk_percent")
            if isinstance(disk_val, (int, float)):
                self.query_one("#bar-disk", MetricBar).set_value(float(disk_val))

            # 更新信息面板
            info_parts: list[str] = []
            load_avg = data.get("load_avg")
            if isinstance(load_avg, str):
                info_parts.append(f"  Load Average: {load_avg}")

            mem_used = data.get("memory_used_mb")
            mem_total = data.get("memory_total_mb")
            if isinstance(mem_used, (int, float)) and isinstance(
                mem_total, (int, float)
            ):
                info_parts.append(
                    f"  Memory: {int(mem_used)}MB / {int(mem_total)}MB"
                )

            disk_used = data.get("disk_used_gb")
            disk_total = data.get("disk_total_gb")
            if isinstance(disk_used, (int, float)) and isinstance(
                disk_total, (int, float)
            ):
                info_parts.append(
                    f"  Disk: {disk_used:.1f}GB / {disk_total:.1f}GB"
                )

            info_parts.append(f"  Refresh: #{self._tick_count}")

            info_content = self.query_one("#info-content", Static)
            info_content.update("\n".join(info_parts) if info_parts else "No data")

        except Exception as e:
            info_content = self.query_one("#info-content", Static)
            info_content.update(f"Error: {e}")
