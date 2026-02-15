"""分析模板缓存 - 从 AnalyzeWorker 提取的缓存管理逻辑"""

from __future__ import annotations

import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


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


# 预置的默认分析命令模板
# 使用 {name} 作为占位符
# 端口检查命令按 OS 区分（macOS 没有 ss/netstat -p）
_IS_MACOS = platform.system() == "Darwin"

_PORT_COMMANDS_MACOS: list[str] = [
    "lsof -iTCP:{name} -sTCP:LISTEN -P -n",
    "lsof -i :{name} -P -n",
    "curl -sI http://localhost:{name} --max-time 3 || true",
]

_PORT_COMMANDS_LINUX: list[str] = [
    "ss -tlnp | grep :{name}",
    "lsof -i :{name} -P -n",
    "curl -sI http://localhost:{name} --max-time 3 || true",
]

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
    "port": _PORT_COMMANDS_MACOS if _IS_MACOS else _PORT_COMMANDS_LINUX,
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
