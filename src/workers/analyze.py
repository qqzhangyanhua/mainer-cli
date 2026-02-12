"""智能分析 Worker"""

from __future__ import annotations

import json
import re
from typing import Optional

from src.llm.client import LLMClient
from src.types import ArgValue, WorkerResult
from src.workers.analyze_cache import (
    AnalyzeTemplate,
    AnalyzeTemplateCache,
    DEFAULT_ANALYZE_COMMANDS,
)
from src.workers.base import BaseWorker
from src.workers.shell import ShellWorker

# 向后兼容：保持 from src.workers.analyze import XYZ 可用
__all__ = [
    "AnalyzeWorker",
    "AnalyzeTemplate",
    "AnalyzeTemplateCache",
    "DEFAULT_ANALYZE_COMMANDS",
]


class AnalyzeWorker(BaseWorker):
    """智能分析 Worker

    支持的操作:
    - explain: 分析并解释运维对象（Docker 容器、进程、端口等）

    工作流程:
    1. 获取分析步骤（命令列表）- 优先从缓存获取
    2. 执行命令收集信息
    3. 调用 LLM 生成分析总结
    """

    def __init__(
        self,
        llm_client: LLMClient,
        cache: Optional[AnalyzeTemplateCache] = None,
    ) -> None:
        """初始化 AnalyzeWorker

        Args:
            llm_client: LLM 客户端，用于生成分析步骤和总结
            cache: 分析模板缓存，默认使用全局缓存
        """
        self._llm_client = llm_client
        self._shell_worker = ShellWorker()
        self._cache = cache or AnalyzeTemplateCache()

    @property
    def name(self) -> str:
        return "analyze"

    def get_capabilities(self) -> list[str]:
        return ["explain"]

    def _detect_target_type(self, target_name: str) -> str:
        """根据目标名称猜测对象类型

        用于用户未明确指定类型时的 fallback

        Args:
            target_name: 对象名称

        Returns:
            推测的对象类型
        """
        # 纯数字 - 可能是 PID 或端口
        if target_name.isdigit():
            port = int(target_name)
            # 常见端口范围判断
            if 1 <= port <= 65535:
                # 常见服务端口倾向于 port，较大数字倾向于 PID
                if port < 1024 or port in [3000, 3306, 5432, 6379, 8080, 8443, 9000, 27017]:
                    return "port"
            return "process"

        # 以 / 开头 - 文件路径
        if target_name.startswith("/"):
            return "file"

        # .service 结尾 - systemd
        if target_name.endswith(".service"):
            return "systemd"

        # 包含网络接口常见名称
        network_prefixes = ["eth", "en", "wlan", "lo", "br-", "docker", "veth"]
        for prefix in network_prefixes:
            if target_name.startswith(prefix):
                return "network"

        # 默认假设 docker 容器（最常见场景）
        return "docker"

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行分析操作

        Args:
            action: 动作名称，目前仅支持 "explain"
            args: 参数字典
                - target: 分析对象名称（如容器名、PID、端口号）
                - type: 对象类型（docker、process、port、file、systemd）

        Returns:
            WorkerResult: 分析结果
        """
        if action != "explain":
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        target = args.get("target", "")
        target_type = args.get("type", "")

        # 目标为空时，请求澄清
        if not target:
            return WorkerResult(
                success=False,
                message="请指定要分析的对象名称（如容器名、进程 PID、端口号等）",
                task_completed=False,
            )

        target_str = str(target)
        type_str = str(target_type) if target_type else ""

        # 类型为空时，尝试自动检测
        if not type_str:
            type_str = self._detect_target_type(target_str)

        # 1. 获取分析步骤（命令列表）
        commands = await self._get_analyze_commands(type_str, target_str)

        if not commands:
            return WorkerResult(
                success=False,
                message=f"无法生成分析步骤，请检查对象类型是否正确: {type_str}",
                task_completed=False,
            )

        # 2. 执行命令收集信息
        collected_info = await self._collect_info(commands, target_str)

        # 检查是否所有命令都失败
        all_failed = all(output.startswith("[Failed:") for output in collected_info.values())
        if all_failed:
            return WorkerResult(
                success=False,
                message=f"无法收集 {target_str} 的信息，所有命令执行失败",
                task_completed=False,
            )

        # 3. 调用 LLM 总结分析
        summary = await self._generate_summary(type_str, target_str, collected_info)

        return WorkerResult(
            success=True,
            message=summary,
            task_completed=True,
        )

    async def _get_analyze_commands(
        self,
        target_type: str,
        target_name: str,
    ) -> list[str]:
        """获取分析命令列表

        优先级：缓存 > 预置默认 > LLM 生成

        Args:
            target_type: 对象类型
            target_name: 对象名称

        Returns:
            命令列表
        """
        # 1. 尝试从缓存获取
        if target_type:
            cached = self._cache.get(target_type)
            if cached:
                return cached

        # 2. 使用预置默认命令
        if target_type and target_type in DEFAULT_ANALYZE_COMMANDS:
            return DEFAULT_ANALYZE_COMMANDS[target_type]

        # 3. 未知类型，调用 LLM 生成
        commands = await self._generate_commands_via_llm(target_type, target_name)

        # 4. 存入缓存供下次使用（仅当有类型且成功生成时）
        if target_type and commands:
            self._cache.set(target_type, commands)

        return commands

    async def _generate_commands_via_llm(
        self,
        target_type: str,
        target_name: str,
    ) -> list[str]:
        """调用 LLM 生成分析步骤

        Args:
            target_type: 对象类型
            target_name: 对象名称

        Returns:
            命令列表
        """
        type_hint = f" of type '{target_type}'" if target_type else ""
        prompt = f"""Generate shell commands to analyze an object{type_hint} named "{target_name}".

Return ONLY a JSON array of command strings, no explanation or markdown.
Commands should be safe (read-only) and gather useful diagnostic info.
Use {{name}} as placeholder for the object name.

Example for docker:
["docker inspect {{name}}", "docker logs --tail 50 {{name}}"]

Example for process (PID):
["ps aux | grep {{name}}", "lsof -p {{name}} 2>/dev/null | head -50"]

Example for port:
["lsof -i :{{name}}", "ss -tlnp | grep :{{name}}"]

Your response (JSON array only):"""

        response = await self._llm_client.generate(
            "You are a Linux ops expert. Output only valid JSON.",
            prompt,
        )

        return self._parse_command_list(response)

    def _parse_command_list(self, response: str) -> list[str]:
        """解析 LLM 返回的命令列表

        Args:
            response: LLM 响应文本

        Returns:
            命令列表
        """
        # 尝试提取 JSON 数组
        # 先尝试去除 markdown 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.strip()

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return [str(cmd) for cmd in parsed if isinstance(cmd, str)]
        except json.JSONDecodeError:
            pass

        return []

    async def _collect_info(
        self,
        commands: list[str],
        target_name: str,
    ) -> dict[str, str]:
        """执行命令收集信息

        Args:
            commands: 命令列表（可包含 {name} 占位符）
            target_name: 对象名称

        Returns:
            命令 -> 输出 的映射
        """
        results: dict[str, str] = {}

        for cmd_template in commands:
            # 替换占位符
            actual_cmd = cmd_template.replace("{name}", target_name)

            result = await self._shell_worker.execute(
                "execute_command",
                {"command": actual_cmd},
            )

            if result.success and result.data and isinstance(result.data, dict):
                raw_output = result.data.get("raw_output")
                if raw_output and isinstance(raw_output, str):
                    results[actual_cmd] = raw_output
                else:
                    results[actual_cmd] = result.message
            else:
                results[actual_cmd] = f"[Failed: {result.message}]"

        return results

    async def _generate_summary(
        self,
        target_type: str,
        target_name: str,
        collected_info: dict[str, str],
    ) -> str:
        """调用 LLM 生成分析总结

        Args:
            target_type: 对象类型
            target_name: 对象名称
            collected_info: 命令 -> 输出 的映射

        Returns:
            分析总结文本
        """
        info_text = "\n\n".join(
            [f"=== {cmd} ===\n{output}" for cmd, output in collected_info.items()]
        )

        type_hint = f" ({target_type})" if target_type else ""
        prompt = f"""Analyze this object "{target_name}"{type_hint} based on the following command outputs:

{info_text}

Provide a concise Chinese summary explaining:
1. What this object is and its purpose
2. Key configuration details (ports, volumes, environment, etc. if applicable)
3. Current status and any notable observations

Keep the summary under 200 words. Use natural language.
If some commands failed, mention what info is missing but still provide analysis based on available data."""

        return await self._llm_client.generate(
            "You are an expert ops engineer. Provide clear, actionable analysis in Chinese.",
            prompt,
        )
