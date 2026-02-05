"""智能分析 Worker

包含：
- AnalyzeWorker: 智能分析 Worker
- AnalyzeTemplate: 分析模板数据类
- AnalyzeTemplateCache: 分析模板缓存管理器（内部实现）
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.llm.client import LLMClient
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.shell import ShellWorker


# ============================================================
# 缓存相关类型和管理器（内部实现，供 CLI cache 命令使用）
# ============================================================


class AnalyzeTemplate(BaseModel):
    """分析模板

    存储 LLM 生成的分析命令列表，供后续复用
    """

    commands: list[str] = Field(..., description="命令列表，支持 {name} 占位符")
    created_at: str = Field(..., description="创建时间 ISO 格式")
    hit_count: int = Field(default=0, description="命中次数")


class AnalyzeTemplateCache:
    """分析模板缓存管理器

    存储位置: ~/.opsai/cache/analyze_templates.json

    缓存策略:
    - 首次分析某类型对象时生成，永久有效
    - 用户可通过 CLI 命令手动清除
    - 不设过期时间（分析步骤相对稳定）
    """

    DEFAULT_CACHE_PATH = Path.home() / ".opsai" / "cache" / "analyze_templates.json"

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        """初始化缓存管理器

        Args:
            cache_path: 缓存文件路径，默认 ~/.opsai/cache/analyze_templates.json
        """
        self._cache_path = cache_path or self.DEFAULT_CACHE_PATH
        self._templates: dict[str, AnalyzeTemplate] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载缓存

        缓存读取失败时不阻塞主流程，直接使用空缓存
        """
        if not self._cache_path.exists():
            return

        try:
            with self._cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for key, value in data.items():
                    if isinstance(value, dict):
                        self._templates[key] = AnalyzeTemplate(**value)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            # 缓存损坏时忽略，不阻塞主流程
            self._templates = {}

    def _save(self) -> None:
        """保存缓存到文件"""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_path.open("w", encoding="utf-8") as f:
                data = {k: v.model_dump() for k, v in self._templates.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            # 保存失败时静默处理，不阻塞主流程
            pass

    def get(self, target_type: str) -> Optional[list[str]]:
        """获取分析模板

        Args:
            target_type: 对象类型（docker, process, port 等）

        Returns:
            命令列表，不存在返回 None
        """
        template = self._templates.get(target_type)
        if template:
            template.hit_count += 1
            self._save()
            return template.commands
        return None

    def set(self, target_type: str, commands: list[str]) -> None:
        """设置分析模板

        Args:
            target_type: 对象类型
            commands: 命令列表
        """
        self._templates[target_type] = AnalyzeTemplate(
            commands=commands,
            created_at=datetime.now().isoformat(),
            hit_count=0,
        )
        self._save()

    def clear(self, target_type: Optional[str] = None) -> int:
        """清除缓存

        Args:
            target_type: 指定类型，None 表示清除全部

        Returns:
            清除的模板数量
        """
        if target_type:
            if target_type in self._templates:
                del self._templates[target_type]
                self._save()
                return 1
            return 0
        else:
            count = len(self._templates)
            self._templates = {}
            self._save()
            return count

    def list_all(self) -> dict[str, AnalyzeTemplate]:
        """列出所有缓存模板

        Returns:
            类型 -> 模板 的映射
        """
        return self._templates.copy()

    def exists(self, target_type: str) -> bool:
        """检查模板是否存在

        Args:
            target_type: 对象类型

        Returns:
            是否存在
        """
        return target_type in self._templates


# ============================================================
# 预置默认分析命令模板
# ============================================================

# 预置的默认分析命令模板
# 使用 {name} 作为占位符
DEFAULT_ANALYZE_COMMANDS: dict[str, list[str]] = {
    "docker": [
        "docker inspect {name}",
        "docker logs --tail 50 {name}",
    ],
    "process": [
        "ps aux | grep {name}",
        "lsof -p {name} 2>/dev/null | head -50",
        "cat /proc/{name}/cmdline 2>/dev/null | tr '\\0' ' '",
    ],
    "port": [
        "lsof -i :{name}",
        "ss -tlnp | grep :{name}",
        "netstat -tlnp 2>/dev/null | grep :{name}",
    ],
    "file": [
        "file {name}",
        "ls -la {name}",
        "stat {name}",
        "head -20 {name} 2>/dev/null",
    ],
    "systemd": [
        "systemctl status {name}",
        "journalctl -u {name} --no-pager -n 30",
        "systemctl cat {name} 2>/dev/null",
    ],
    "network": [
        "ss -tlnp | grep {name}",
        "netstat -an 2>/dev/null | grep {name}",
        "ip addr show {name} 2>/dev/null",
    ],
}


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
