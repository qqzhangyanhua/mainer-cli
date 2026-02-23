# Inventory Context Injection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Read `~/.opsai/inventory.md` and inject its content into every system prompt so the LLM always knows the server topology.

**Architecture:** Single-point change in `PromptBuilder.build_system_prompt()` — read file, concat string, done. No new classes, no config, no abstractions.

**Tech Stack:** Python pathlib, pytest (tmp_path + monkeypatch)

---

### Task 1: Write failing tests for inventory injection

**Files:**
- Modify: `tests/test_prompt.py`

**Step 1: Write the failing tests**

Add two test methods to `TestPromptBuilder`:

```python
def test_inventory_injected_when_file_exists(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inventory.md 存在时，system prompt 包含其内容"""
    inventory_file = tmp_path / "inventory.md"
    inventory_file.write_text(
        "# 生产环境\n## 服务器 A (192.168.1.100)\n- Nginx: /opt/html\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.orchestrator.prompt.INVENTORY_PATH", inventory_file
    )

    builder = PromptBuilder()
    context = EnvironmentContext()
    prompt = builder.build_system_prompt(context)

    assert "Server inventory" in prompt
    assert "192.168.1.100" in prompt
    assert "/opt/html" in prompt

def test_inventory_not_injected_when_file_missing(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """inventory.md 不存在时，system prompt 无 inventory 段"""
    missing_file = tmp_path / "inventory.md"
    monkeypatch.setattr(
        "src.orchestrator.prompt.INVENTORY_PATH", missing_file
    )

    builder = PromptBuilder()
    context = EnvironmentContext()
    prompt = builder.build_system_prompt(context)

    assert "Server inventory" not in prompt
```

Note: Import `Path` from `pathlib` and `pytest` at the top of the file.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompt.py::TestPromptBuilder::test_inventory_injected_when_file_exists tests/test_prompt.py::TestPromptBuilder::test_inventory_not_injected_when_file_missing -v`

Expected: FAIL with `AttributeError: module 'src.orchestrator.prompt' has no attribute 'INVENTORY_PATH'`

**Step 3: Commit**

```bash
git add tests/test_prompt.py
git commit -m "test: add inventory context injection tests"
```

---

### Task 2: Implement inventory injection in PromptBuilder

**Files:**
- Modify: `src/orchestrator/prompt.py:1-10,120-142`

**Step 1: Add import and module-level constant**

At the top of `src/orchestrator/prompt.py`, add `Path` import and the constant:

```python
from pathlib import Path
```

After the existing imports (before `class PromptBuilder`), add:

```python
INVENTORY_PATH: Path = Path("~/.opsai/inventory.md").expanduser()
```

**Step 2: Add inventory reading logic in `build_system_prompt()`**

After line 120 (`env_context = context.to_prompt_context()`), insert:

```python
        # 服务器资产台账注入
        inventory_section = ""
        if INVENTORY_PATH.exists():
            content = INVENTORY_PATH.read_text(encoding="utf-8").strip()
            if content:
                inventory_section = (
                    "\n\n## Server inventory (infrastructure context)\n"
                    + content
                )
```

**Step 3: Insert `{inventory_section}` into the prompt template**

In the f-string template, change:

```
{env_context}

## How you work (ReAct loop)
```

to:

```
{env_context}
{inventory_section}

## How you work (ReAct loop)
```

**Step 4: Run all tests to verify they pass**

Run: `uv run pytest tests/test_prompt.py -v`

Expected: ALL PASS

**Step 5: Run full test suite to check for regressions**

Run: `uv run pytest --tb=short`

Expected: No new failures

**Step 6: Run type check**

Run: `uv run mypy src/orchestrator/prompt.py`

Expected: No errors

**Step 7: Commit**

```bash
git add src/orchestrator/prompt.py tests/test_prompt.py
git commit -m "feat: inject ~/.opsai/inventory.md into system prompt as server context"
```
