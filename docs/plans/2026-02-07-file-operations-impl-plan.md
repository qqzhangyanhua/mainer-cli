# SystemWorker 文件操作扩展 - 详细实现计划

> 基于 `2026-02-07-file-operations-design.md` 设计文档
> 预计总工期：4-6 小时
> 涉及文件：4 个修改 + 1 个新建

---

## 📋 任务总览

| # | 任务 | 文件 | 预计耗时 | 依赖 |
|---|------|------|---------|------|
| 1 | SystemWorker 新增 3 个 action | `src/workers/system.py` | 2h | 无 |
| 2 | 更新 Prompt 能力描述 | `src/orchestrator/prompt.py` | 30min | 无 |
| 3 | 单元测试 | `tests/test_workers_system.py` | 1.5h | Task 1 |
| 4 | 集成测试 | `tests/test_file_operations.py`（新建） | 1h | Task 1, 2 |
| 5 | 验证 & 代码质量检查 | - | 30min | Task 1-4 |

---

## Task 1：SystemWorker 新增 3 个 action

**文件**：`src/workers/system.py`

### 1.1 更新 `get_capabilities()` 返回值

**当前代码**（第 31 行）：
```python
def get_capabilities(self) -> list[str]:
    return ["list_files", "find_large_files", "check_disk_usage", "delete_files"]
```

**修改为**：
```python
def get_capabilities(self) -> list[str]:
    return [
        "list_files", "find_large_files", "check_disk_usage", "delete_files",
        "write_file", "append_to_file", "replace_in_file",
    ]
```

### 1.2 更新 `execute()` 中的 handlers 字典

**当前代码**（第 47-53 行）：
```python
handlers: dict[...] = {
    "list_files": self._list_files,
    "find_large_files": self._find_large_files,
    "check_disk_usage": self._check_disk_usage,
    "delete_files": self._delete_files,
}
```

**修改为**：
```python
handlers: dict[...] = {
    "list_files": self._list_files,
    "find_large_files": self._find_large_files,
    "check_disk_usage": self._check_disk_usage,
    "delete_files": self._delete_files,
    "write_file": self._write_file,
    "append_to_file": self._append_to_file,
    "replace_in_file": self._replace_in_file,
}
```

### 1.3 实现 `_write_file` 方法

在 `_delete_files` 方法之后添加，预计约 60 行代码。

**实现要点**：
- 参数验证：`path`（必需，str）、`content`（必需，str）
- dry-run：返回内容长度 + 内容预览（前 200 字符）
- 错误处理：
  - 父目录不存在 → `success=False, message="Parent directory does not exist: ..."`
  - 权限不足 → `success=False, message="Permission denied: ..."`
  - 路径是目录 → `success=False, message="Path is a directory: ..."`
- 正常写入使用 `Path.write_text(content, encoding="utf-8")`
- 返回 `task_completed=True`

**伪代码**：
```python
async def _write_file(
    self,
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    # 1. 参数验证
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(success=False, message="path parameter is required and must be a string")

    content = args.get("content")
    if not isinstance(content, str):
        return WorkerResult(success=False, message="content parameter is required and must be a string")

    path = Path(path_str)

    # 2. 路径是目录检查
    if path.is_dir():
        return WorkerResult(success=False, message=f"Path is a directory: {path}")

    # 3. 父目录存在检查
    if not path.parent.exists():
        return WorkerResult(success=False, message=f"Parent directory does not exist: {path.parent}")

    # 4. dry-run 处理
    if dry_run:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return WorkerResult(
            success=True,
            message=f"[DRY-RUN] Would write {len(content)} chars to {path}\nContent preview:\n{preview}",
            simulated=True,
        )

    # 5. 实际写入
    try:
        path.write_text(content, encoding="utf-8")
        return WorkerResult(
            success=True,
            data={"path": str(path), "size": len(content)},
            message=f"Successfully wrote {len(content)} chars to {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error writing file: {e!s}")
```

### 1.4 实现 `_append_to_file` 方法

在 `_write_file` 之后添加，预计约 45 行代码。

**实现要点**：
- 参数验证：`path`（必需，str）、`content`（必需，str）
- **要求文件已存在**（区分"追加"和"创建"语义）
- dry-run：返回追加内容长度 + 内容预览
- 错误处理：
  - 文件不存在 → `success=False, message="File not found: ..."`
  - 权限不足 → `success=False, message="Permission denied: ..."`
- 正常追加使用 `open(path, "a", encoding="utf-8")` 模式

**伪代码**：
```python
async def _append_to_file(
    self,
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    # 1. 参数验证
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(success=False, message="path parameter is required and must be a string")

    content = args.get("content")
    if not isinstance(content, str):
        return WorkerResult(success=False, message="content parameter is required and must be a string")

    path = Path(path_str)

    # 2. 文件存在检查
    if not path.exists():
        return WorkerResult(success=False, message=f"File not found: {path}")

    if not path.is_file():
        return WorkerResult(success=False, message=f"Path is not a file: {path}")

    # 3. dry-run 处理
    if dry_run:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return WorkerResult(
            success=True,
            message=f"[DRY-RUN] Would append {len(content)} chars to {path}\nContent to append:\n{preview}",
            simulated=True,
        )

    # 4. 实际追加
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return WorkerResult(
            success=True,
            data={"path": str(path), "appended_size": len(content)},
            message=f"Successfully appended {len(content)} chars to {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error appending to file: {e!s}")
```

### 1.5 实现 `_replace_in_file` 方法

在 `_append_to_file` 之后添加，预计约 75 行代码。

**实现要点**：
- 参数验证：`path`（必需，str）、`old`（必需，str）、`new`（必需，str）、`regex`（可选，bool，默认 False）、`count`（可选，int，默认全部替换）
- dry-run：返回匹配数量 + 替换预览
- 精确匹配模式：使用 `str.replace()` 或 `str.count()` + 循环
- 正则匹配模式：使用 `re.sub()` 或 `re.subn()`
- 错误处理：
  - 文件不存在 → `success=False, message="File not found: ..."`
  - 无匹配 → `success=True, message="No matches found for '...'"`（注意：无匹配是 success=True）
  - 正则语法错误 → `success=False, message="Invalid regex pattern: [error]"`
- 读取文件内容，执行替换，写回文件

**伪代码**：
```python
async def _replace_in_file(
    self,
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    import re

    # 1. 参数验证
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(success=False, message="path parameter is required and must be a string")

    old = args.get("old")
    if not isinstance(old, str):
        return WorkerResult(success=False, message="old parameter is required and must be a string")

    new = args.get("new")
    if not isinstance(new, str):
        return WorkerResult(success=False, message="new parameter is required and must be a string")

    use_regex = args.get("regex", False)
    if isinstance(use_regex, str):
        use_regex = use_regex.lower() == "true"

    max_count = args.get("count")
    if max_count is not None and not isinstance(max_count, int):
        return WorkerResult(success=False, message="count must be an integer")

    path = Path(path_str)

    # 2. 文件存在检查
    if not path.exists():
        return WorkerResult(success=False, message=f"File not found: {path}")

    if not path.is_file():
        return WorkerResult(success=False, message=f"Path is not a file: {path}")

    # 3. 读取文件内容
    try:
        content = path.read_text(encoding="utf-8")
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error reading file: {e!s}")

    # 4. 计算匹配数量并执行替换
    if use_regex:
        try:
            pattern = re.compile(old)
        except re.error as e:
            return WorkerResult(success=False, message=f"Invalid regex pattern: {e!s}")

        matches = pattern.findall(content)
        match_count = len(matches)

        if match_count == 0:
            return WorkerResult(
                success=True,
                message=f"No matches found for '{old}'",
                task_completed=True,
            )

        if dry_run:
            effective_count = min(match_count, max_count) if max_count else match_count
            return WorkerResult(
                success=True,
                message=(
                    f'[DRY-RUN] Would replace in {path}\n'
                    f'  "{old}" → "{new}"\n'
                    f'  Matches found: {match_count}, would replace: {effective_count}'
                ),
                simulated=True,
            )

        count_arg = max_count if max_count else 0  # re.sub: count=0 表示全部替换
        new_content, actual_count = re.subn(old, new, content, count=count_arg)
    else:
        match_count = content.count(old)

        if match_count == 0:
            return WorkerResult(
                success=True,
                message=f"No matches found for '{old}'",
                task_completed=True,
            )

        if dry_run:
            effective_count = min(match_count, max_count) if max_count else match_count
            return WorkerResult(
                success=True,
                message=(
                    f'[DRY-RUN] Would replace in {path}\n'
                    f'  "{old}" → "{new}"\n'
                    f'  Matches found: {match_count}, would replace: {effective_count}'
                ),
                simulated=True,
            )

        if max_count:
            new_content = content.replace(old, new, max_count)
            actual_count = min(match_count, max_count)
        else:
            new_content = content.replace(old, new)
            actual_count = match_count

    # 5. 写回文件
    try:
        path.write_text(new_content, encoding="utf-8")
        return WorkerResult(
            success=True,
            data={"path": str(path), "replacements": actual_count},
            message=f"Replaced {actual_count} occurrence(s) in {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error writing file: {e!s}")
```

### 1.6 更新类注释

**当前**（第 14-22 行）：
```python
class SystemWorker(BaseWorker):
    """系统文件操作 Worker

    支持的操作:
    - list_files: 列出目录下的文件
    - find_large_files: 查找大文件
    - check_disk_usage: 检查磁盘使用情况
    - delete_files: 删除文件
    """
```

**修改为**：
```python
class SystemWorker(BaseWorker):
    """系统文件操作 Worker

    支持的操作:
    - list_files: 列出目录下的文件
    - find_large_files: 查找大文件
    - check_disk_usage: 检查磁盘使用情况
    - delete_files: 删除文件
    - write_file: 创建或覆写文件
    - append_to_file: 追加内容到文件
    - replace_in_file: 查找替换文件内容
    """
```

### 1.7 新增 import

在文件顶部的 imports 中添加 `import re`（用于 `replace_in_file` 的正则功能）。

**注意**：也可以选择在 `_replace_in_file` 方法内部 `import re`，减少顶层 import。设计文档未指定，建议放在顶层以符合常规 Python 风格。

---

## Task 2：更新 Prompt 能力描述

**文件**：`src/orchestrator/prompt.py`

### 2.1 更新 `WORKER_CAPABILITIES` 字典

**当前代码**（第 23 行）：
```python
"system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
```

**修改为**：
```python
"system": [
    "list_files", "find_large_files", "check_disk_usage", "delete_files",
    "write_file", "append_to_file", "replace_in_file",
],
```

### 2.2 更新 `build_system_prompt` 中的 Worker Details

在 `build_system_prompt` 方法返回的 Prompt 模板中，`- system/container: Avoid these - use shell commands instead` 这一行**之前**，添加以下内容：

```
- system.write_file: Create or overwrite a file
  - args: {{"path": "string", "content": "string"}}
  - risk_level: medium (new file), high (overwrite existing)
  - Example: {{"worker": "system", "action": "write_file", "args": {{"path": ".env", "content": "TOKEN=xxxx"}}, "risk_level": "medium"}}

- system.append_to_file: Append content to existing file
  - args: {{"path": "string", "content": "string"}}
  - risk_level: medium
  - Example: {{"worker": "system", "action": "append_to_file", "args": {{"path": ".env", "content": "\\nAPI_KEY=zzzz"}}, "risk_level": "medium"}}

- system.replace_in_file: Find and replace text in file
  - args: {{"path": "string", "old": "string", "new": "string", "regex": bool (optional, default false), "count": int (optional)}}
  - risk_level: high
  - Example: {{"worker": "system", "action": "replace_in_file", "args": {{"path": ".env", "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"}}, "risk_level": "high"}}
```

### 2.3 更新示例工作流

在 `build_system_prompt` 方法的 Example workflows 部分，追加文件操作的示例：

```
User: "新建一个.env文件写入TOKEN=xxxx"
Step 1: {{"worker": "system", "action": "write_file", "args": {{"path": ".env", "content": "TOKEN=xxxx"}}, "risk_level": "medium"}}

User: "把.env的TOKEN换成yyyy"
Step 1: {{"worker": "system", "action": "replace_in_file", "args": {{"path": ".env", "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"}}, "risk_level": "high"}}

User: "在.env增加API_KEY=zzzz"
Step 1: {{"worker": "system", "action": "append_to_file", "args": {{"path": ".env", "content": "\\nAPI_KEY=zzzz"}}, "risk_level": "medium"}}
```

---

## Task 3：单元测试

**文件**：`tests/test_workers_system.py`（修改现有文件，追加测试用例）

### 3.1 write_file 测试用例

```python
# === write_file 测试 ===

@pytest.mark.asyncio
async def test_write_file_creates_new_file(self, tmp_path: Path) -> None:
    """测试创建新文件"""
    worker = SystemWorker()
    target = tmp_path / "test.env"

    result = await worker.execute(
        "write_file",
        {"path": str(target), "content": "TOKEN=xxxx"},
    )

    assert result.success is True
    assert result.task_completed is True
    assert target.exists()
    assert target.read_text() == "TOKEN=xxxx"

@pytest.mark.asyncio
async def test_write_file_overwrites_existing(self, tmp_path: Path) -> None:
    """测试覆写已有文件"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("OLD_CONTENT")

    result = await worker.execute(
        "write_file",
        {"path": str(target), "content": "NEW_CONTENT"},
    )

    assert result.success is True
    assert target.read_text() == "NEW_CONTENT"

@pytest.mark.asyncio
async def test_write_file_dry_run(self, tmp_path: Path) -> None:
    """测试 write_file dry-run 模式"""
    worker = SystemWorker()
    target = tmp_path / "test.env"

    result = await worker.execute(
        "write_file",
        {"path": str(target), "content": "TOKEN=xxxx", "dry_run": True},
    )

    assert result.success is True
    assert result.simulated is True
    assert "[DRY-RUN]" in result.message
    assert "10 chars" in result.message  # len("TOKEN=xxxx") == 10
    assert not target.exists()  # 文件不应被创建

@pytest.mark.asyncio
async def test_write_file_parent_not_exists(self, tmp_path: Path) -> None:
    """测试父目录不存在"""
    worker = SystemWorker()
    target = tmp_path / "nonexistent" / "test.env"

    result = await worker.execute(
        "write_file",
        {"path": str(target), "content": "TOKEN=xxxx"},
    )

    assert result.success is False
    assert "Parent directory does not exist" in result.message

@pytest.mark.asyncio
async def test_write_file_path_is_directory(self, tmp_path: Path) -> None:
    """测试路径是目录"""
    worker = SystemWorker()

    result = await worker.execute(
        "write_file",
        {"path": str(tmp_path), "content": "TOKEN=xxxx"},
    )

    assert result.success is False
    assert "Path is a directory" in result.message
```

### 3.2 append_to_file 测试用例

```python
# === append_to_file 测试 ===

@pytest.mark.asyncio
async def test_append_to_file_success(self, tmp_path: Path) -> None:
    """测试追加内容"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=xxxx")

    result = await worker.execute(
        "append_to_file",
        {"path": str(target), "content": "\nAPI_KEY=zzzz"},
    )

    assert result.success is True
    assert result.task_completed is True
    assert target.read_text() == "TOKEN=xxxx\nAPI_KEY=zzzz"

@pytest.mark.asyncio
async def test_append_to_file_dry_run(self, tmp_path: Path) -> None:
    """测试 append_to_file dry-run 模式"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=xxxx")

    result = await worker.execute(
        "append_to_file",
        {"path": str(target), "content": "\nAPI_KEY=zzzz", "dry_run": True},
    )

    assert result.success is True
    assert result.simulated is True
    assert "[DRY-RUN]" in result.message
    assert target.read_text() == "TOKEN=xxxx"  # 内容不应被修改

@pytest.mark.asyncio
async def test_append_to_file_not_exists(self, tmp_path: Path) -> None:
    """测试追加到不存在的文件"""
    worker = SystemWorker()
    target = tmp_path / "nonexistent.env"

    result = await worker.execute(
        "append_to_file",
        {"path": str(target), "content": "API_KEY=zzzz"},
    )

    assert result.success is False
    assert "File not found" in result.message
```

### 3.3 replace_in_file 测试用例

```python
# === replace_in_file 测试 ===

@pytest.mark.asyncio
async def test_replace_in_file_exact_match(self, tmp_path: Path) -> None:
    """测试精确匹配替换"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=old_value\nAPI_KEY=keep")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "TOKEN=old_value", "new": "TOKEN=new_value"},
    )

    assert result.success is True
    assert result.task_completed is True
    content = target.read_text()
    assert "TOKEN=new_value" in content
    assert "API_KEY=keep" in content

@pytest.mark.asyncio
async def test_replace_in_file_multiple_matches(self, tmp_path: Path) -> None:
    """测试多处匹配全部替换"""
    worker = SystemWorker()
    target = tmp_path / "config.txt"
    target.write_text("host=localhost\ndb_host=localhost\nredis_host=localhost")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "localhost", "new": "192.168.1.100"},
    )

    assert result.success is True
    content = target.read_text()
    assert content.count("192.168.1.100") == 3
    assert "localhost" not in content

@pytest.mark.asyncio
async def test_replace_in_file_with_count(self, tmp_path: Path) -> None:
    """测试限定替换次数"""
    worker = SystemWorker()
    target = tmp_path / "config.txt"
    target.write_text("AAA\nAAA\nAAA")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "AAA", "new": "BBB", "count": 2},
    )

    assert result.success is True
    content = target.read_text()
    assert content.count("BBB") == 2
    assert content.count("AAA") == 1

@pytest.mark.asyncio
async def test_replace_in_file_regex(self, tmp_path: Path) -> None:
    """测试正则表达式替换"""
    worker = SystemWorker()
    target = tmp_path / "config.txt"
    target.write_text("PORT=8080\nPORT=3000\nPORT=5432")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": r"PORT=\d+", "new": "PORT=9999", "regex": True},
    )

    assert result.success is True
    content = target.read_text()
    assert content == "PORT=9999\nPORT=9999\nPORT=9999"

@pytest.mark.asyncio
async def test_replace_in_file_no_match(self, tmp_path: Path) -> None:
    """测试无匹配情况"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=xxxx")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "NONEXISTENT", "new": "REPLACEMENT"},
    )

    assert result.success is True  # 无匹配是 success=True
    assert "No matches found" in result.message
    assert target.read_text() == "TOKEN=xxxx"  # 内容未变

@pytest.mark.asyncio
async def test_replace_in_file_invalid_regex(self, tmp_path: Path) -> None:
    """测试无效正则表达式"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=xxxx")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "[invalid", "new": "replacement", "regex": True},
    )

    assert result.success is False
    assert "Invalid regex pattern" in result.message

@pytest.mark.asyncio
async def test_replace_in_file_dry_run(self, tmp_path: Path) -> None:
    """测试 replace_in_file dry-run 模式"""
    worker = SystemWorker()
    target = tmp_path / "test.env"
    target.write_text("TOKEN=old\nTOKEN=old")

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "TOKEN=old", "new": "TOKEN=new", "dry_run": True},
    )

    assert result.success is True
    assert result.simulated is True
    assert "[DRY-RUN]" in result.message
    assert "Matches found: 2" in result.message
    assert target.read_text() == "TOKEN=old\nTOKEN=old"  # 内容不应被修改

@pytest.mark.asyncio
async def test_replace_in_file_file_not_found(self, tmp_path: Path) -> None:
    """测试替换不存在的文件"""
    worker = SystemWorker()
    target = tmp_path / "nonexistent.env"

    result = await worker.execute(
        "replace_in_file",
        {"path": str(target), "old": "TOKEN", "new": "KEY"},
    )

    assert result.success is False
    assert "File not found" in result.message
```

---

## Task 4：集成测试

**文件**：`tests/test_file_operations.py`（新建）

测试端到端的文件操作工作流，模拟用户真实场景。

```python
"""文件操作集成测试

测试用户通过自然语言触发的文件操作工作流。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.workers.system import SystemWorker


class TestFileOperationsWorkflow:
    """文件操作工作流集成测试"""

    @pytest.mark.asyncio
    async def test_create_env_file_workflow(self, tmp_path: Path) -> None:
        """场景：新建一个.env文件并写入TOKEN=xxxx

        模拟用户说"新建一个.env文件写入TOKEN=xxxx"
        Orchestrator 生成 write_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"

        # Step 1: 创建文件
        result = await worker.execute(
            "write_file",
            {"path": str(env_file), "content": "TOKEN=xxxx\n"},
        )

        assert result.success is True
        assert env_file.exists()
        assert env_file.read_text() == "TOKEN=xxxx\n"

    @pytest.mark.asyncio
    async def test_replace_env_value_workflow(self, tmp_path: Path) -> None:
        """场景：把.env的TOKEN换成yyyy

        模拟用户说"把.env的TOKEN换成yyyy"
        Orchestrator 生成 replace_in_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=xxxx\nAPI_KEY=zzzz\n")

        # Step 1: 替换值
        result = await worker.execute(
            "replace_in_file",
            {"path": str(env_file), "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"},
        )

        assert result.success is True
        content = env_file.read_text()
        assert "TOKEN=yyyy" in content
        assert "API_KEY=zzzz" in content  # 其他内容不受影响

    @pytest.mark.asyncio
    async def test_append_env_field_workflow(self, tmp_path: Path) -> None:
        """场景：在.env文件增加API_KEY=zzzz

        模拟用户说"在.env增加API_KEY=zzzz"
        Orchestrator 生成 append_to_file 指令
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=xxxx\n")

        # Step 1: 追加内容
        result = await worker.execute(
            "append_to_file",
            {"path": str(env_file), "content": "API_KEY=zzzz\n"},
        )

        assert result.success is True
        content = env_file.read_text()
        assert "TOKEN=xxxx\n" in content
        assert "API_KEY=zzzz\n" in content

    @pytest.mark.asyncio
    async def test_full_env_management_workflow(self, tmp_path: Path) -> None:
        """完整工作流：创建 → 追加 → 替换

        模拟完整的 .env 文件管理场景：
        1. 创建 .env 并写入 TOKEN=xxxx
        2. 追加 API_KEY=zzzz
        3. 将 TOKEN 的值换成 yyyy
        """
        worker = SystemWorker()
        env_file = tmp_path / ".env"

        # Step 1: 创建
        r1 = await worker.execute(
            "write_file",
            {"path": str(env_file), "content": "TOKEN=xxxx\n"},
        )
        assert r1.success is True

        # Step 2: 追加
        r2 = await worker.execute(
            "append_to_file",
            {"path": str(env_file), "content": "API_KEY=zzzz\n"},
        )
        assert r2.success is True

        # Step 3: 替换
        r3 = await worker.execute(
            "replace_in_file",
            {"path": str(env_file), "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"},
        )
        assert r3.success is True

        # 验证最终内容
        final_content = env_file.read_text()
        assert "TOKEN=yyyy" in final_content
        assert "API_KEY=zzzz" in final_content
        assert "TOKEN=xxxx" not in final_content
```

---

## Task 5：验证 & 代码质量检查

### 5.1 运行测试

```bash
# 运行所有测试
uv run pytest -v

# 仅运行新增测试
uv run pytest tests/test_workers_system.py -v -k "write_file or append_to_file or replace_in_file"
uv run pytest tests/test_file_operations.py -v

# 运行带覆盖率
uv run pytest --cov=src/workers/system --cov-report=term-missing
```

### 5.2 代码质量

```bash
# 类型检查
uv run mypy src/workers/system.py
uv run mypy src/orchestrator/prompt.py

# 格式化
uv run ruff format src/workers/system.py src/orchestrator/prompt.py
uv run ruff format tests/test_workers_system.py tests/test_file_operations.py

# Lint
uv run ruff check src/workers/system.py src/orchestrator/prompt.py
uv run ruff check tests/test_workers_system.py tests/test_file_operations.py
```

### 5.3 检查清单

- [ ] `src/workers/system.py` 添加了 3 个新方法：`_write_file`、`_append_to_file`、`_replace_in_file`
- [ ] `get_capabilities()` 返回包含新 actions
- [ ] `execute()` handlers 字典包含新 actions
- [ ] `src/orchestrator/prompt.py` 的 `WORKER_CAPABILITIES` 已更新
- [ ] `build_system_prompt` 的 Worker Details 已添加新 action 描述
- [ ] `build_system_prompt` 的示例工作流已添加文件操作示例
- [ ] 所有新方法都有完整的 dry-run 支持
- [ ] 所有新方法都有完整的错误处理
- [ ] 类型标注完整，无 `any` 类型
- [ ] `tests/test_workers_system.py` 包含 15 个新测试用例
- [ ] `tests/test_file_operations.py` 包含 4 个集成测试
- [ ] 所有测试通过：`uv run pytest -v`
- [ ] 类型检查通过：`uv run mypy src/`
- [ ] Lint 检查通过：`uv run ruff check src/ tests/`
- [ ] 现有测试未被破坏

---

## 📁 变更文件汇总

| 文件 | 操作 | 变更行数（估计） |
|------|------|----------------|
| `src/workers/system.py` | 修改 | +180 行（3 个新方法 + 更新 capabilities/handlers/docstring） |
| `src/orchestrator/prompt.py` | 修改 | +25 行（能力描述 + Worker Details + 示例） |
| `tests/test_workers_system.py` | 修改 | +180 行（15 个新测试用例） |
| `tests/test_file_operations.py` | 新建 | ~120 行（4 个集成测试） |

**总计**：约 505 行新增代码

---

## ⚠️ 注意事项

1. **类型安全**：所有新方法的 `data` 返回值必须符合 `WorkerResult.data` 的类型签名：`Union[list[dict[str, Union[str, int]]], dict[str, Union[str, int, bool]], None]`。注意 `write_file` 和 `append_to_file` 返回 `dict[str, Union[str, int]]` 类型的 `data`，需要用 `cast()` 确保类型兼容。

2. **编码一致性**：所有文件读写操作统一使用 `encoding="utf-8"`。

3. **现有测试兼容**：`test_capabilities` 测试用例需要检查是否会因为新增 capabilities 而影响断言。当前测试只用 `in` 检查，不会受影响。

4. **`replace_in_file` 的 re 模块**：可以选择在文件顶部 `import re` 或在方法内部局部 import。建议顶部 import 以保持一致性。

5. **`data` 字段中的 `replacements` 值**：`WorkerResult.data` 的 dict 形式是 `dict[str, Union[str, int, bool]]`，`replacements` 返回 `int` 类型是兼容的。

6. **权限测试**：`test_write_file_permission_denied` 未包含在单元测试中，因为在 CI 环境中模拟权限不足较复杂（需要修改文件权限或使用 mock）。如需覆盖，可额外添加基于 `unittest.mock.patch` 的测试。

---

## 🔄 执行顺序

```
Step 1: 修改 src/workers/system.py （Task 1.1 ~ 1.7）
Step 2: 修改 src/orchestrator/prompt.py （Task 2.1 ~ 2.3）
Step 3: 修改 tests/test_workers_system.py （Task 3.1 ~ 3.3）
Step 4: 新建 tests/test_file_operations.py （Task 4）
Step 5: 运行验证 （Task 5）
```

Task 1 和 Task 2 可以并行执行（无依赖关系）。
Task 3 和 Task 4 依赖 Task 1 的实现。
Task 5 依赖所有前置任务完成。
