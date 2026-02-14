"""通知分发 Worker - Webhook + 桌面通知"""

from __future__ import annotations

import platform
import subprocess
from typing import Optional, Union

import httpx

from src.types import (
    AlertEvent,
    AlertSeverity,
    ArgValue,
    NotificationChannel,
    WorkerResult,
)
from src.workers.base import BaseWorker


class NotifierWorker(BaseWorker):
    """通知分发 Worker

    支持的操作:
    - send: 发送告警通知到所有匹配渠道
    - test: 发送测试通知验证渠道配置
    """

    def __init__(
        self,
        channels: Optional[list[NotificationChannel]] = None,
    ) -> None:
        self._channels = channels or []

    @property
    def name(self) -> str:
        return "notifier"

    def get_capabilities(self) -> list[str]:
        return ["send", "test"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        if action == "send":
            return await self._send(args)
        if action == "test":
            return await self._test(args)
        return WorkerResult(success=False, message=f"Unknown action: {action}")

    async def _send(self, args: dict[str, ArgValue]) -> WorkerResult:
        """发送告警通知"""
        message = str(args.get("message", ""))
        severity_raw = str(args.get("severity", "warning"))
        severity: AlertSeverity = "critical" if severity_raw == "critical" else "warning"
        title = str(args.get("title", "OpsAI Alert"))
        recovered = bool(args.get("recovered", False))

        if not message:
            return WorkerResult(success=False, message="缺少参数: message")

        sent_count = 0
        errors: list[str] = []

        for channel in self._channels:
            # 检查渠道是否订阅了此严重级别
            if severity not in channel.events:
                continue

            try:
                if channel.type == "webhook":
                    await self._send_webhook(channel, title, message, severity, recovered)
                    sent_count += 1
                elif channel.type == "desktop":
                    self._send_desktop(title, message, severity)
                    sent_count += 1
            except Exception as exc:
                errors.append(f"{channel.type}: {exc}")

        if errors and sent_count == 0:
            return WorkerResult(
                success=False,
                message=f"通知发送全部失败: {'; '.join(errors)}",
            )

        status = "恢复" if recovered else "告警"
        error_note = f" (部分失败: {'; '.join(errors)})" if errors else ""
        return WorkerResult(
            success=True,
            message=f"{status}通知已发送到 {sent_count} 个渠道{error_note}",
            task_completed=True,
        )

    async def _test(self, args: dict[str, ArgValue]) -> WorkerResult:
        """发送测试通知"""
        test_message = "This is a test notification from OpsAI."
        test_args: dict[str, ArgValue] = {
            "message": test_message,
            "severity": "warning",
            "title": "OpsAI Test",
        }
        return await self._send(test_args)

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    async def _send_webhook(
        self,
        channel: NotificationChannel,
        title: str,
        message: str,
        severity: AlertSeverity,
        recovered: bool,
    ) -> None:
        if not channel.url:
            raise ValueError("Webhook URL not configured")

        # 通用 JSON payload（兼容大多数 webhook 平台）
        payload = self._build_webhook_payload(
            channel.url, title, message, severity, recovered
        )

        headers = {"Content-Type": "application/json"}
        if channel.headers:
            headers.update(channel.headers)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(channel.url, json=payload, headers=headers)
            resp.raise_for_status()

    def _build_webhook_payload(
        self,
        url: str,
        title: str,
        message: str,
        severity: AlertSeverity,
        recovered: bool,
    ) -> dict[str, Union[str, list[dict[str, str]]]]:
        """根据 URL 猜测平台，构建对应 payload"""
        icon = "[Recovered]" if recovered else f"[{severity.upper()}]"
        full_message = f"{icon} {title}\n{message}"

        # 钉钉
        if "dingtalk" in url or "oapi.dingtalk.com" in url:
            return {
                "msgtype": "text",
                "text": {"content": full_message},
            }

        # 飞书
        if "feishu" in url or "open.feishu.cn" in url:
            return {
                "msg_type": "text",
                "content": {"text": full_message},
            }

        # Slack
        if "hooks.slack.com" in url:
            return {"text": full_message}

        # 企业微信
        if "qyapi.weixin.qq.com" in url:
            return {
                "msgtype": "text",
                "text": {"content": full_message},
            }

        # 通用格式
        return {
            "title": f"{icon} {title}",
            "message": message,
            "severity": severity,
            "recovered": str(recovered),
        }

    # ------------------------------------------------------------------
    # Desktop notification
    # ------------------------------------------------------------------
    def _send_desktop(
        self, title: str, message: str, severity: AlertSeverity
    ) -> None:
        system = platform.system()

        if system == "Darwin":
            # macOS: osascript
            script = (
                f'display notification "{message}" '
                f'with title "{title}" '
                f'sound name "{"Sosumi" if severity == "critical" else "Pop"}"'
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
        elif system == "Linux":
            # Linux: notify-send
            urgency = "critical" if severity == "critical" else "normal"
            subprocess.run(
                ["notify-send", f"--urgency={urgency}", title, message],
                capture_output=True,
                timeout=5,
            )
        # Windows/other: 静默忽略


class AlertManager:
    """告警状态管理器

    负责：
    - 判断指标是否触发告警
    - 防抖（连续 N 次才触发）
    - 冷却（告警后一段时间不重复通知）
    - 恢复检测
    """

    def __init__(
        self,
        duration: int = 3,
        cooldown: int = 300,
    ) -> None:
        self._duration = duration
        self._cooldown = cooldown
        # metric_name -> 连续触发次数
        self._trigger_counts: dict[str, int] = {}
        # metric_name -> 是否处于告警状态
        self._alerting: dict[str, bool] = {}
        # metric_name -> 上次告警时间戳（monotonic）
        self._last_alert_time: dict[str, float] = {}

    def check_metric(
        self,
        metric_name: str,
        value: float,
        warning_threshold: float,
        critical_threshold: float,
        current_time: float,
    ) -> Optional[AlertEvent]:
        """检查指标是否触发告警

        Returns:
            AlertEvent 如果需要发送通知，None 如果不需要
        """
        # 判定严重级别
        severity: Optional[AlertSeverity] = None
        threshold = 0.0
        if value >= critical_threshold:
            severity = "critical"
            threshold = critical_threshold
        elif value >= warning_threshold:
            severity = "warning"
            threshold = warning_threshold

        was_alerting = self._alerting.get(metric_name, False)

        if severity is not None:
            # 指标超阈值
            self._trigger_counts[metric_name] = self._trigger_counts.get(metric_name, 0) + 1

            if self._trigger_counts[metric_name] >= self._duration:
                # 达到防抖次数
                last_time = self._last_alert_time.get(metric_name, 0.0)
                if current_time - last_time >= self._cooldown or not was_alerting:
                    # 冷却期已过或首次告警
                    self._alerting[metric_name] = True
                    self._last_alert_time[metric_name] = current_time
                    return AlertEvent(
                        rule_name=f"auto_{metric_name}",
                        metric_name=metric_name,
                        current_value=value,
                        threshold=threshold,
                        severity=severity,
                        message=f"{metric_name} = {value:.1f} (阈值: {threshold:.1f})",
                        recovered=False,
                    )
        else:
            # 指标正常
            self._trigger_counts[metric_name] = 0

            if was_alerting:
                # 从告警恢复
                self._alerting[metric_name] = False
                return AlertEvent(
                    rule_name=f"auto_{metric_name}",
                    metric_name=metric_name,
                    current_value=value,
                    threshold=warning_threshold,
                    severity="warning",
                    message=f"{metric_name} 已恢复正常: {value:.1f}",
                    recovered=True,
                )

        return None
