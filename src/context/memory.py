"""会话记忆 — 跨会话上下文持久化"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """单条记忆"""

    key: str = Field(..., description="记忆键名")
    value: str = Field(..., description="记忆内容")
    category: str = Field(default="fact", description="分类: fact/preference/note")
    created_at: float = Field(default_factory=time.time, description="创建时间戳")
    updated_at: float = Field(default_factory=time.time, description="更新时间戳")
    hit_count: int = Field(default=0, description="命中次数")


class SessionMemory:
    """跨会话记忆管理器

    存储环境事实、用户偏好和笔记，在会话间持久化。
    存储路径: ~/.opsai/memory.json

    分类:
    - fact: 环境事实（如 "has_nginx=true", "db_type=postgres"）
    - preference: 用户偏好（如 "preferred_editor=vim"）
    - note: 用户笔记（如 "redis 端口改为 6380"）
    """

    MAX_ENTRIES = 200

    def __init__(self, memory_path: Optional[Path] = None) -> None:
        self._path = memory_path or Path.home() / ".opsai" / "memory.json"
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        """从磁盘加载记忆"""
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key, entry_data in data.items():
                    self._entries[key] = MemoryEntry.model_validate(entry_data)
        except (json.JSONDecodeError, ValueError):
            pass

    def _save(self) -> None:
        """持久化到磁盘"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.model_dump() for k, v in self._entries.items()}
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def remember(
        self,
        key: str,
        value: str,
        category: str = "fact",
    ) -> None:
        """记住一条信息

        Args:
            key: 记忆键名（如 "env.nginx", "pref.editor"）
            value: 记忆内容
            category: 分类
        """
        now = time.time()
        if key in self._entries:
            entry = self._entries[key]
            entry.value = value
            entry.updated_at = now
        else:
            self._entries[key] = MemoryEntry(
                key=key,
                value=value,
                category=category,
                created_at=now,
                updated_at=now,
            )

        self._enforce_limit()
        self._save()

    def recall(self, key: str) -> Optional[str]:
        """回忆一条信息

        Args:
            key: 记忆键名

        Returns:
            记忆内容，不存在返回 None
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        entry.hit_count += 1
        return entry.value

    def forget(self, key: str) -> bool:
        """忘记一条信息

        Returns:
            是否成功删除
        """
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def search(self, query: str, category: Optional[str] = None) -> list[MemoryEntry]:
        """搜索记忆

        Args:
            query: 搜索关键词（在 key 和 value 中模糊匹配）
            category: 可选分类过滤

        Returns:
            匹配的记忆列表
        """
        query_lower = query.lower()
        results: list[MemoryEntry] = []
        for entry in self._entries.values():
            if category and entry.category != category:
                continue
            if query_lower in entry.key.lower() or query_lower in entry.value.lower():
                results.append(entry)
        return sorted(results, key=lambda e: e.hit_count, reverse=True)

    def list_all(self, category: Optional[str] = None) -> list[MemoryEntry]:
        """列出所有记忆

        Args:
            category: 可选分类过滤

        Returns:
            记忆列表（按更新时间排序）
        """
        entries = list(self._entries.values())
        if category:
            entries = [e for e in entries if e.category == category]
        return sorted(entries, key=lambda e: e.updated_at, reverse=True)

    def get_context_prompt(self, max_entries: int = 20) -> str:
        """生成用于注入 LLM 的上下文提示

        选取最相关的记忆（高频 + 最近更新）拼接为文本。

        Args:
            max_entries: 最大条目数

        Returns:
            上下文文本
        """
        if not self._entries:
            return ""

        # 按 hit_count * 0.3 + recency * 0.7 综合排序
        now = time.time()
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._entries.values():
            recency = max(0, 1 - (now - entry.updated_at) / (86400 * 30))
            score = entry.hit_count * 0.3 + recency * 0.7
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_entries]

        if not top:
            return ""

        lines = ["Known context from previous sessions:"]
        for _, entry in top:
            prefix = {"fact": "Fact", "preference": "Pref", "note": "Note"}.get(
                entry.category, "Info"
            )
            lines.append(f"- [{prefix}] {entry.key}: {entry.value}")

        return "\n".join(lines)

    def clear(self, category: Optional[str] = None) -> int:
        """清空记忆

        Args:
            category: 可选分类过滤，None 清空全部

        Returns:
            删除的条目数
        """
        if category is None:
            count = len(self._entries)
            self._entries.clear()
        else:
            keys_to_del = [
                k for k, v in self._entries.items() if v.category == category
            ]
            count = len(keys_to_del)
            for k in keys_to_del:
                del self._entries[k]

        self._save()
        return count

    @property
    def size(self) -> int:
        return len(self._entries)

    def _enforce_limit(self) -> None:
        """超出上限时淘汰最旧最少使用的条目"""
        if len(self._entries) <= self.MAX_ENTRIES:
            return

        # 按 (hit_count, updated_at) 排序，淘汰最低的
        sorted_keys = sorted(
            self._entries.keys(),
            key=lambda k: (
                self._entries[k].hit_count,
                self._entries[k].updated_at,
            ),
        )
        while len(self._entries) > self.MAX_ENTRIES:
            del self._entries[sorted_keys.pop(0)]
