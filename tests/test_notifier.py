"""NotifierWorker + AlertManager 单元测试"""

from __future__ import annotations

import pytest

from src.types import NotificationChannel
from src.workers.notifier import AlertManager, NotifierWorker


# ------------------------------------------------------------------
# AlertManager 测试
# ------------------------------------------------------------------


@pytest.fixture
def alert_mgr() -> AlertManager:
    return AlertManager(duration=3, cooldown=60)


def test_alert_no_trigger_below_threshold(alert_mgr: AlertManager) -> None:
    """阈值以下不触发"""
    event = alert_mgr.check_metric("cpu", 50.0, 80.0, 95.0, 0.0)
    assert event is None


def test_alert_no_trigger_insufficient_duration(alert_mgr: AlertManager) -> None:
    """未达到防抖次数不触发"""
    event1 = alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, 0.0)
    assert event1 is None
    event2 = alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, 1.0)
    assert event2 is None


def test_alert_triggers_after_duration(alert_mgr: AlertManager) -> None:
    """达到防抖次数后触发"""
    alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, 0.0)
    alert_mgr.check_metric("cpu", 86.0, 80.0, 95.0, 1.0)
    event = alert_mgr.check_metric("cpu", 87.0, 80.0, 95.0, 2.0)
    assert event is not None
    assert event.severity == "warning"
    assert event.recovered is False
    assert "cpu" in event.metric_name


def test_alert_critical_severity(alert_mgr: AlertManager) -> None:
    """critical 级别正确触发"""
    for t in range(3):
        event = alert_mgr.check_metric("cpu", 96.0, 80.0, 95.0, float(t))
    assert event is not None
    assert event.severity == "critical"


def test_alert_cooldown(alert_mgr: AlertManager) -> None:
    """冷却期内不重复告警"""
    # 先触发告警
    for t in range(3):
        alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, float(t))

    # 冷却期内（t=10 < cooldown=60）继续超阈值
    event = alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, 10.0)
    assert event is None


def test_alert_retrigger_after_cooldown(alert_mgr: AlertManager) -> None:
    """冷却期过后可以重新告警"""
    for t in range(3):
        alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, float(t))

    # 冷却期过后（t=70 > cooldown=60），首次检查即触发
    event = alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, 70.0)
    assert event is not None
    assert event.severity == "warning"


def test_alert_recovery(alert_mgr: AlertManager) -> None:
    """从告警恢复时发送恢复通知"""
    # 先进入告警状态
    for t in range(3):
        alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, float(t))

    # 恢复正常
    event = alert_mgr.check_metric("cpu", 50.0, 80.0, 95.0, 10.0)
    assert event is not None
    assert event.recovered is True


def test_alert_no_recovery_if_not_alerting(alert_mgr: AlertManager) -> None:
    """非告警状态下恢复不发通知"""
    event = alert_mgr.check_metric("cpu", 50.0, 80.0, 95.0, 0.0)
    assert event is None


def test_alert_independent_metrics(alert_mgr: AlertManager) -> None:
    """不同指标独立计数"""
    for t in range(3):
        alert_mgr.check_metric("cpu", 85.0, 80.0, 95.0, float(t))

    # memory 还没触发过
    event = alert_mgr.check_metric("memory", 85.0, 80.0, 95.0, 0.0)
    assert event is None


# ------------------------------------------------------------------
# NotifierWorker 测试
# ------------------------------------------------------------------


@pytest.fixture
def notifier() -> NotifierWorker:
    return NotifierWorker(channels=[
        NotificationChannel(type="desktop", events=["warning", "critical"]),
    ])


def test_notifier_name(notifier: NotifierWorker) -> None:
    assert notifier.name == "notifier"


def test_notifier_capabilities(notifier: NotifierWorker) -> None:
    caps = notifier.get_capabilities()
    assert "send" in caps
    assert "test" in caps


@pytest.mark.asyncio
async def test_notifier_missing_message(notifier: NotifierWorker) -> None:
    result = await notifier.execute("send", {"severity": "warning"})
    assert result.success is False
    assert "缺少参数" in result.message


@pytest.mark.asyncio
async def test_notifier_unknown_action(notifier: NotifierWorker) -> None:
    result = await notifier.execute("nonexistent", {})
    assert result.success is False


@pytest.mark.asyncio
async def test_notifier_no_channels() -> None:
    """无渠道时也不报错"""
    worker = NotifierWorker(channels=[])
    result = await worker.execute("send", {"message": "test", "severity": "warning"})
    # 无渠道匹配，发送 0 个
    assert result.success is True
    assert "0 个渠道" in result.message


@pytest.mark.asyncio
async def test_notifier_desktop_channel(notifier: NotifierWorker) -> None:
    """desktop 通知不报错（即使不在桌面环境）"""
    result = await notifier.execute("send", {
        "message": "CPU is high",
        "severity": "warning",
        "title": "Test Alert",
    })
    # desktop 发送可能成功也可能静默失败，但不应 crash
    assert isinstance(result.success, bool)


@pytest.mark.asyncio
async def test_notifier_severity_filter() -> None:
    """渠道只接收订阅级别的通知"""
    worker = NotifierWorker(channels=[
        NotificationChannel(type="desktop", events=["critical"]),
    ])
    result = await worker.execute("send", {
        "message": "mild warning",
        "severity": "warning",
    })
    # warning 不在 events 中，0 个渠道
    assert result.success is True
    assert "0 个渠道" in result.message


# ------------------------------------------------------------------
# Webhook payload 构建测试
# ------------------------------------------------------------------


def test_webhook_payload_slack(notifier: NotifierWorker) -> None:
    payload = notifier._build_webhook_payload(
        "https://hooks.slack.com/services/xxx",
        "Alert", "CPU high", "critical", False,
    )
    assert "text" in payload


def test_webhook_payload_dingtalk(notifier: NotifierWorker) -> None:
    payload = notifier._build_webhook_payload(
        "https://oapi.dingtalk.com/robot/send",
        "Alert", "CPU high", "warning", False,
    )
    assert payload["msgtype"] == "text"


def test_webhook_payload_feishu(notifier: NotifierWorker) -> None:
    payload = notifier._build_webhook_payload(
        "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
        "Alert", "Disk full", "critical", True,
    )
    assert payload["msg_type"] == "text"
    assert "Recovered" in str(payload["content"])


def test_webhook_payload_generic(notifier: NotifierWorker) -> None:
    payload = notifier._build_webhook_payload(
        "https://example.com/webhook",
        "Alert", "Memory high", "warning", False,
    )
    assert "message" in payload
    assert "severity" in payload
