"""预处理器监控意图测试"""

from __future__ import annotations

from src.orchestrator.preprocessor import RequestPreprocessor


class TestPreprocessorMonitorIntent:
    """测试 monitor 意图检测"""

    def setup_method(self) -> None:
        self.preprocessor = RequestPreprocessor()

    def test_monitor_intent_system_status(self) -> None:
        result = self.preprocessor.preprocess("系统状态怎么样")
        assert result.intent == "monitor"
        assert result.confidence == "high"
        assert result.enriched_input is not None
        assert "monitor.snapshot" in result.enriched_input

    def test_monitor_intent_health(self) -> None:
        result = self.preprocessor.preprocess("系统健康吗")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_monitor_intent_english(self) -> None:
        result = self.preprocessor.preprocess("system status")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_monitor_intent_system_health(self) -> None:
        result = self.preprocessor.preprocess("system health check")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_monitor_intent_resource_usage(self) -> None:
        result = self.preprocessor.preprocess("资源使用情况")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_monitor_intent_system_load(self) -> None:
        result = self.preprocessor.preprocess("系统负载高不高")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_monitor_intent_cpu_memory(self) -> None:
        result = self.preprocessor.preprocess("cpu和内存怎么样")
        assert result.intent == "monitor"
        assert result.confidence == "high"

    def test_non_monitor_intent_container(self) -> None:
        result = self.preprocessor.preprocess("查看容器")
        assert result.intent != "monitor"

    def test_non_monitor_intent_greeting(self) -> None:
        result = self.preprocessor.preprocess("你好")
        assert result.intent != "monitor"

    def test_non_monitor_intent_deploy(self) -> None:
        result = self.preprocessor.preprocess("部署 https://github.com/user/repo")
        assert result.intent != "monitor"
