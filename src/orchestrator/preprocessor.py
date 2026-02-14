"""请求预处理器 - 在 LLM 之前解析意图和指代"""

from __future__ import annotations

import re
from typing import Optional

from src.types import (
    AnalyzeTargetType,
    ConversationEntry,
    PreprocessConfidence,
    PreprocessedRequest,
    PreprocessIntent,
    get_raw_output,
)

# 意图检测模式
EXPLAIN_PATTERNS: list[str] = [
    r"是干嘛的",
    r"有什么用",
    r"是什么",
    r"干什么的",
    r"什么意思",
    r"解释",
    r"分析",
    r"explain",
    r"what is",
    r"what's",
    r"用途",
    r"作用",
    r"干嘛",
]

LIST_PATTERNS: list[str] = [
    r"列出",
    r"有哪些",
    r"显示",
    r"查看",
    r"list",
    r"show",
    r"我有",
]

GREETING_PATTERNS: list[str] = [
    r"^你好",
    r"^hi$",
    r"^hello",
    r"^hey",
    r"^嗨",
]

# 自我介绍/身份询问模式（优先级高于 explain）
IDENTITY_PATTERNS: list[str] = [
    r"你是谁",
    r"你是誰",
    r"你是什么",
    r"你是什麼",
    r"你是干嘛的",
    r"你是幹嘛的",
    r"你是做什么的",
    r"你是做什麼的",
    r"你是干什么的",
    r"你是幹什麼的",
    r"你叫什么",
    r"你叫什麼",
]
# 部署意图模式
DEPLOY_PATTERNS: list[str] = [
    r"部署",
    r"deploy",
    r"安装",
    r"install",
    r"启动",
    r"运行",
    r"跑起来",
    r"run\s",
    r"start",
]

# 监控/系统状态意图模式
MONITOR_PATTERNS: list[str] = [
    r"系统状态",
    r"系统健康",
    r"系统资源",
    r"系统概况",
    r"系统负载",
    r"system\s*status",
    r"system\s*health",
    r"cpu.*内存|内存.*cpu",
    r"资源使用",
]

# GitHub/GitLab URL 模式
REPO_URL_PATTERN = r"https?://(?:github|gitlab)\.com/[\w\-\.]+/[\w\-\.]+"

# 指代词模式
REFERENCE_PATTERNS: list[str] = [
    r"这个",
    r"那个",
    r"它",
    r"这",
    r"那",
    r"this",
    r"that",
]

# 对象类型关键词映射
TYPE_KEYWORDS: dict[str, AnalyzeTargetType] = {
    "docker": "docker",
    "容器": "docker",
    "container": "docker",
    "进程": "process",
    "process": "process",
    "pid": "process",
    "端口": "port",
    "port": "port",
    "文件": "file",
    "file": "file",
    "服务": "systemd",
    "service": "systemd",
    "systemd": "systemd",
    "网络": "network",
    "network": "network",
}


class RequestPreprocessor:
    """请求预处理器

    职责：
    1. 意图检测 - 识别用户真正想做什么
    2. 指代解析 - 将"这个"、"它"等代词解析为实际对象名
    3. 类型推断 - 推断目标对象类型（docker、process、port 等）

    当置信度足够高时，可以直接生成 Instruction，绕过 LLM 推理。
    """

    def preprocess(
        self,
        user_input: str,
        history: Optional[list[ConversationEntry]] = None,
    ) -> PreprocessedRequest:
        """预处理用户请求

        Args:
            user_input: 用户输入
            history: 对话历史

        Returns:
            预处理后的请求
        """
        # 1. 意图检测
        intent = self._detect_intent(user_input)

        # 2. 自我介绍/身份询问 - 直接返回高置信度
        if intent == "identity":
            return PreprocessedRequest(
                original_input=user_input,
                intent=intent,
                confidence="high",
            )

        # 2.5 监控/系统状态 - 快速路径，引导 LLM 调用 monitor.snapshot
        if intent == "monitor":
            return PreprocessedRequest(
                original_input=user_input,
                intent=intent,
                confidence="high",
                enriched_input=(
                    "用户想查看系统整体状态。请使用 monitor.snapshot 获取 CPU、内存、磁盘、"
                    "负载的完整快照，然后用 chat.respond 总结结果。"
                ),
            )

        # 3. 如果是解释意图，尝试解析目标
        if intent == "explain":
            target, target_type, confidence = self._resolve_target(user_input, history)

            if target and confidence in ["high", "medium"]:
                return PreprocessedRequest(
                    original_input=user_input,
                    intent=intent,
                    confidence=confidence,
                    resolved_target=target,
                    target_type=target_type,
                )

            # 检测「需要先获取上下文」的模式
            # 用户有解释意图但无法解析目标，需要先列出再分析
            if confidence == "medium" and target_type and not target:
                return PreprocessedRequest(
                    original_input=user_input,
                    intent=intent,
                    confidence="medium",
                    target_type=target_type,
                    needs_context=True,  # 标记需要先获取上下文
                )

        # 4. 低置信度或其他意图，返回原始请求
        return PreprocessedRequest(
            original_input=user_input,
            intent=intent,
            confidence="low",
        )

    def extract_repo_url(self, text: str) -> Optional[str]:
        """从文本中提取仓库 URL

        Args:
            text: 用户输入文本

        Returns:
            仓库 URL，未找到返回 None
        """
        match = re.search(REPO_URL_PATTERN, text)
        return match.group(0) if match else None

    def _has_deploy_intent(self, text: str) -> bool:
        """检测是否有部署意图"""
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in DEPLOY_PATTERNS)

    def _detect_intent(self, text: str) -> PreprocessIntent:
        """检测用户意图

        优先级: deploy > identity > monitor > explain > greeting > list > unknown
        """
        text_lower = text.lower()

        # 检查部署意图（优先级最高）
        # 条件：包含仓库 URL 且有部署关键词
        has_repo_url = re.search(REPO_URL_PATTERN, text) is not None
        has_deploy_keywords = self._has_deploy_intent(text)

        if has_repo_url and has_deploy_keywords:
            return "deploy"

        # 检查自我介绍/身份询问
        for pattern in IDENTITY_PATTERNS:
            if re.search(pattern, text_lower):
                return "identity"

        # 检查监控/系统状态意图
        for pattern in MONITOR_PATTERNS:
            if re.search(pattern, text_lower):
                return "monitor"

        # 检查解释意图
        for pattern in EXPLAIN_PATTERNS:
            if re.search(pattern, text_lower):
                return "explain"

        # 检查问候意图
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return "greeting"

        # 检查列表意图
        for pattern in LIST_PATTERNS:
            if re.search(pattern, text_lower):
                return "list"

        return "unknown"

    def _resolve_target(
        self,
        user_input: str,
        history: Optional[list[ConversationEntry]],
    ) -> tuple[Optional[str], Optional[AnalyzeTargetType], PreprocessConfidence]:
        """解析目标对象

        Returns:
            (目标名称, 目标类型, 置信度)
        """
        # 1. 先检测类型（从用户输入中）
        target_type = self._detect_type(user_input)

        # 2. 检查是否有指代词
        has_reference = any(re.search(pattern, user_input) for pattern in REFERENCE_PATTERNS)

        # 3. 如果有指代词，从历史中提取目标
        if has_reference and history:
            target = self._extract_target_from_history(history, target_type)
            if target:
                # 如果没有从输入中检测到类型，尝试从历史推断
                if not target_type:
                    target_type = self._infer_type_from_history(history)
                return (target, target_type or "docker", "high")

        # 4. 检查"只有一个"模式 - 意味着用户已知列表只有一项
        only_one_pattern = r"只有一个|就一个|唯一一个|only one"
        if re.search(only_one_pattern, user_input) and history:
            target = self._extract_target_from_history(history, target_type)
            if target:
                if not target_type:
                    target_type = self._infer_type_from_history(history)
                return (target, target_type or "docker", "high")

        # 5. 尝试从用户输入中直接提取目标名称
        # 例如: "compoder-mongo 是干嘛的"
        explicit_target = self._extract_explicit_target(user_input)
        if explicit_target:
            return (explicit_target, target_type or "docker", "medium")

        # 6. 检测「需要先获取上下文」的模式
        # 用户提到了类型但没有指定具体名称，且没有历史可以解析
        # 例如: "只有1个这个docker是干嘛的" (无历史)
        if has_reference and target_type and not history:
            # 返回特殊标记，让引擎先获取信息
            return (None, target_type, "medium")

        return (None, None, "low")

    def _detect_type(self, text: str) -> Optional[AnalyzeTargetType]:
        """从文本中检测对象类型"""
        text_lower = text.lower()
        for keyword, obj_type in TYPE_KEYWORDS.items():
            if keyword in text_lower:
                return obj_type
        return None

    def _extract_target_from_history(
        self,
        history: list[ConversationEntry],
        target_type: Optional[AnalyzeTargetType],
    ) -> Optional[str]:
        """从历史记录中提取目标对象名称"""
        # 从最近的历史记录开始查找
        for entry in reversed(history):
            result = entry.result
            raw_output = get_raw_output(result)
            if not raw_output:
                continue

            # 根据类型尝试解析
            if target_type == "docker" or target_type is None:
                container = self._parse_docker_output(raw_output)
                if container:
                    return container

            if target_type == "port" or target_type is None:
                port = self._parse_port_output(raw_output)
                if port:
                    return port

        return None

    def _parse_docker_output(self, output: str) -> Optional[str]:
        """解析 docker ps 输出，提取容器名"""
        lines = output.strip().split("\n")
        if len(lines) < 2:
            return None

        # 跳过表头
        data_lines = [line for line in lines[1:] if line.strip()]

        if len(data_lines) == 1:
            # 只有一个容器，提取名称
            # docker ps 输出的最后一列是 NAMES
            parts = data_lines[0].split()
            if parts:
                # 容器名通常是最后一列
                return parts[-1]

        # 多个容器时返回 None（需要用户澄清）
        return None

    def _parse_port_output(self, output: str) -> Optional[str]:
        """解析端口相关输出"""
        # 简单的端口号提取
        match = re.search(r":(\d+)", output)
        if match:
            return match.group(1)
        return None

    def _infer_type_from_history(
        self,
        history: list[ConversationEntry],
    ) -> Optional[AnalyzeTargetType]:
        """从历史记录推断对象类型"""
        for entry in reversed(history):
            instruction = entry.instruction
            command = instruction.args.get("command", "")
            if isinstance(command, str):
                if "docker" in command:
                    return "docker"
                if "lsof" in command or "netstat" in command or "ss " in command:
                    return "port"
                if "ps " in command:
                    return "process"
                if "systemctl" in command:
                    return "systemd"
        return None

    def _extract_explicit_target(self, text: str) -> Optional[str]:
        """从文本中提取显式目标名称

        例如: "compoder-mongo 是干嘛的" -> "compoder-mongo"
        """
        # 匹配 Docker 容器名模式（字母数字下划线短横）
        # 排除常见中文词和关键词
        exclude_words = {
            "docker",
            "容器",
            "服务",
            "端口",
            "进程",
            "文件",
            "这个",
            "那个",
            "是",
            "的",
            "什么",
            "干嘛",
        }

        # 尝试匹配可能的容器名/对象名
        patterns = [
            r"([a-zA-Z][a-zA-Z0-9_-]+)\s*(?:是干嘛|是什么|有什么用)",
            r"(?:分析|解释)\s*([a-zA-Z][a-zA-Z0-9_-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).lower()
                if candidate not in exclude_words:
                    return match.group(1)

        return None
