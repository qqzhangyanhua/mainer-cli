"""预处理器身份询问测试"""

from __future__ import annotations

from src.orchestrator.preprocessor import RequestPreprocessor


def test_identity_intent_detected() -> None:
    preprocessor = RequestPreprocessor()
    result = preprocessor.preprocess("你是谁")
    assert result.intent == "identity"
    assert result.confidence == "high"


def test_identity_over_explain() -> None:
    preprocessor = RequestPreprocessor()
    result = preprocessor.preprocess("你是什么")
    assert result.intent == "identity"
    assert result.confidence == "high"
