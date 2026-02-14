"""DashboardScreen 组件单元测试"""

from __future__ import annotations

import pytest

from src.tui.dashboard import MetricBar, DashboardScreen


# ------------------------------------------------------------------
# MetricBar 测试
# ------------------------------------------------------------------


def test_metric_bar_creation() -> None:
    bar = MetricBar("CPU", value=50.0, bar_id="test-bar")
    assert bar._label == "CPU"
    assert bar._value == 50.0


def test_metric_bar_set_value() -> None:
    bar = MetricBar("Memory", value=0.0, bar_id="test-bar")
    bar._value = 0.0
    bar.set_value(75.5)
    assert bar._value == 75.5


def test_metric_bar_color_thresholds() -> None:
    """验证颜色阈值逻辑"""
    bar = MetricBar("CPU", warn_at=80.0, crit_at=95.0, bar_id="test")

    # 正常
    bar._value = 50.0
    assert bar._value < bar._warn_at

    # 警告
    bar._value = 85.0
    assert bar._value >= bar._warn_at
    assert bar._value < bar._crit_at

    # 严重
    bar._value = 96.0
    assert bar._value >= bar._crit_at


# ------------------------------------------------------------------
# DashboardScreen 初始化测试
# ------------------------------------------------------------------


class FakeMonitor:
    """测试用假 MonitorWorker"""
    pass


def test_dashboard_screen_creation() -> None:
    monitor = FakeMonitor()
    screen = DashboardScreen(
        monitor_worker=monitor,
        interval=5,
        thresholds={"cpu": (70.0, 90.0), "memory": (80.0, 95.0), "disk": (85.0, 95.0)},
    )
    assert screen._interval == 5
    assert screen._thresholds["cpu"] == (70.0, 90.0)


def test_dashboard_screen_default_thresholds() -> None:
    monitor = FakeMonitor()
    screen = DashboardScreen(monitor_worker=monitor)
    assert screen._thresholds["cpu"] == (80.0, 95.0)
    assert screen._thresholds["memory"] == (80.0, 95.0)
    assert screen._thresholds["disk"] == (85.0, 95.0)
