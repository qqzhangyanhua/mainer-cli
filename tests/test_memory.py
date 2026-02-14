"""SessionMemory 单元测试"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.context.memory import MemoryEntry, SessionMemory


@pytest.fixture
def memory(tmp_path: Path) -> SessionMemory:
    return SessionMemory(memory_path=tmp_path / "memory.json")


# ------------------------------------------------------------------
# 基础 CRUD
# ------------------------------------------------------------------


def test_remember_and_recall(memory: SessionMemory) -> None:
    memory.remember("env.nginx", "installed, version 1.24")
    result = memory.recall("env.nginx")
    assert result == "installed, version 1.24"


def test_recall_nonexistent(memory: SessionMemory) -> None:
    assert memory.recall("nonexistent") is None


def test_update_existing(memory: SessionMemory) -> None:
    memory.remember("env.db", "postgres 14")
    memory.remember("env.db", "postgres 16")
    assert memory.recall("env.db") == "postgres 16"


def test_forget(memory: SessionMemory) -> None:
    memory.remember("temp", "data")
    assert memory.forget("temp") is True
    assert memory.recall("temp") is None


def test_forget_nonexistent(memory: SessionMemory) -> None:
    assert memory.forget("nonexistent") is False


# ------------------------------------------------------------------
# 持久化
# ------------------------------------------------------------------


def test_persistence(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    mem1 = SessionMemory(memory_path=path)
    mem1.remember("key1", "value1")
    mem1.remember("key2", "value2", category="preference")

    # 重新加载
    mem2 = SessionMemory(memory_path=path)
    assert mem2.recall("key1") == "value1"
    assert mem2.recall("key2") == "value2"


def test_persistence_file_format(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    mem = SessionMemory(memory_path=path)
    mem.remember("test", "data")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "test" in data
    assert data["test"]["value"] == "data"


# ------------------------------------------------------------------
# 搜索
# ------------------------------------------------------------------


def test_search(memory: SessionMemory) -> None:
    memory.remember("env.nginx", "running on port 80")
    memory.remember("env.redis", "running on port 6379")
    memory.remember("note.todo", "upgrade redis")

    results = memory.search("redis")
    assert len(results) == 2
    keys = {r.key for r in results}
    assert "env.redis" in keys
    assert "note.todo" in keys


def test_search_with_category(memory: SessionMemory) -> None:
    memory.remember("env.nginx", "installed", category="fact")
    memory.remember("note.nginx", "needs update", category="note")

    results = memory.search("nginx", category="fact")
    assert len(results) == 1
    assert results[0].category == "fact"


def test_search_empty(memory: SessionMemory) -> None:
    results = memory.search("nonexistent")
    assert results == []


# ------------------------------------------------------------------
# 列表
# ------------------------------------------------------------------


def test_list_all(memory: SessionMemory) -> None:
    memory.remember("a", "1")
    memory.remember("b", "2")
    memory.remember("c", "3")
    all_entries = memory.list_all()
    assert len(all_entries) == 3


def test_list_by_category(memory: SessionMemory) -> None:
    memory.remember("f1", "v1", category="fact")
    memory.remember("p1", "v2", category="preference")
    memory.remember("f2", "v3", category="fact")

    facts = memory.list_all(category="fact")
    assert len(facts) == 2


# ------------------------------------------------------------------
# 上下文生成
# ------------------------------------------------------------------


def test_context_prompt_empty(memory: SessionMemory) -> None:
    assert memory.get_context_prompt() == ""


def test_context_prompt_with_entries(memory: SessionMemory) -> None:
    memory.remember("env.db", "postgres", category="fact")
    memory.remember("pref.editor", "vim", category="preference")
    memory.remember("note.port", "redis on 6380", category="note")

    prompt = memory.get_context_prompt()
    assert "postgres" in prompt
    assert "vim" in prompt
    assert "6380" in prompt
    assert "Known context" in prompt


def test_context_prompt_max_entries(memory: SessionMemory) -> None:
    for i in range(30):
        memory.remember(f"key{i}", f"value{i}")

    prompt = memory.get_context_prompt(max_entries=5)
    lines = [l for l in prompt.split("\n") if l.startswith("- ")]
    assert len(lines) == 5


# ------------------------------------------------------------------
# 清空
# ------------------------------------------------------------------


def test_clear_all(memory: SessionMemory) -> None:
    memory.remember("a", "1")
    memory.remember("b", "2")
    count = memory.clear()
    assert count == 2
    assert memory.size == 0


def test_clear_by_category(memory: SessionMemory) -> None:
    memory.remember("f1", "v1", category="fact")
    memory.remember("p1", "v2", category="preference")
    count = memory.clear(category="fact")
    assert count == 1
    assert memory.size == 1


# ------------------------------------------------------------------
# 容量限制
# ------------------------------------------------------------------


def test_enforce_limit(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    mem = SessionMemory(memory_path=path)

    # 写入超过 MAX_ENTRIES
    for i in range(SessionMemory.MAX_ENTRIES + 50):
        mem.remember(f"key{i}", f"value{i}")

    assert mem.size <= SessionMemory.MAX_ENTRIES


# ------------------------------------------------------------------
# hit_count
# ------------------------------------------------------------------


def test_hit_count(memory: SessionMemory) -> None:
    memory.remember("test", "data")
    memory.recall("test")
    memory.recall("test")
    memory.recall("test")

    entries = memory.list_all()
    assert entries[0].hit_count == 3
