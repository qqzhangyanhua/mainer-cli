# SystemWorker 文件操作扩展设计

## 概述

在 `SystemWorker` 中新增 3 个通用文件操作 actions，支持用户通过自然语言创建、追加、替换文件内容。

## 用户场景

- "新建一个.env文件并写入TOKEN=xxxx"
- "把.env的TOKEN换成yyyy"
- "在.env文件增加API_KEY=zzzz"

## 新增 Actions

### 1. `write_file` - 创建/覆写文件

```python
args = {
    "path": str,       # 必需，文件路径
    "content": str,    # 必需，文件内容
}
```

- 风险等级：`medium`（创建新文件）/ `high`（覆写已有文件，由 Orchestrator 判断）
- 不自动创建父目录

### 2. `append_to_file` - 追加内容

```python
args = {
    "path": str,       # 必需，文件路径
    "content": str,    # 必需，追加的内容
}
```

- 风险等级：`medium`
- 要求文件已存在

### 3. `replace_in_file` - 查找替换

```python
args = {
    "path": str,       # 必需，文件路径
    "old": str,        # 必需，要替换的文本
    "new": str,        # 必需，替换成的文本
    "regex": bool,     # 可选，默认 False
    "count": int,      # 可选，最多替换次数，默认全部
}
```

- 风险等级：`high`
- 默认精确匹配，`regex=True` 启用正则

## Dry-run 行为

### `write_file`
```
[DRY-RUN] Would write 45 chars to /path/to/.env
Content preview:
TOKEN=xxxx
API_KEY=yyyy
```

### `append_to_file`
```
[DRY-RUN] Would append 20 chars to /path/to/.env
Content to append:
NEW_KEY=value
```

### `replace_in_file`
```
[DRY-RUN] Would replace in /path/to/config.yaml
  "TOKEN=old" → "TOKEN=new"
  Matches found: 2
```

## 错误处理

| Action | 错误场景 | 返回 |
|--------|---------|------|
| `write_file` | 父目录不存在 | `success=False, message="Parent directory does not exist: /path/to"` |
| `write_file` | 权限不足 | `success=False, message="Permission denied: /path/to/.env"` |
| `write_file` | 路径是目录 | `success=False, message="Path is a directory: /path/to"` |
| `append_to_file` | 文件不存在 | `success=False, message="File not found: /path/to/.env"` |
| `replace_in_file` | 文件不存在 | `success=False, message="File not found: /path/to/.env"` |
| `replace_in_file` | 无匹配 | `success=True, message="No matches found for 'old_text'"` |
| `replace_in_file` | 正则语法错误 | `success=False, message="Invalid regex pattern: [error]"` |

## Prompt 模板更新

### WORKER_CAPABILITIES

```python
"system": [
    "list_files", "find_large_files", "check_disk_usage", "delete_files",
    "write_file", "append_to_file", "replace_in_file"  # 新增
],
```

### 系统提示 Worker Details

```
- system.write_file: Create or overwrite a file
  - args: {"path": "string", "content": "string"}
  - risk_level: medium (new file), high (overwrite existing)

- system.append_to_file: Append content to existing file
  - args: {"path": "string", "content": "string"}
  - risk_level: medium

- system.replace_in_file: Find and replace text in file
  - args: {"path": "string", "old": "string", "new": "string", "regex": bool (optional), "count": int (optional)}
  - risk_level: high
```

### 示例工作流

```
User: "新建一个.env文件写入TOKEN=xxxx"
{"worker": "system", "action": "write_file", "args": {"path": ".env", "content": "TOKEN=xxxx"}, "risk_level": "medium"}

User: "把.env的TOKEN换成yyyy"
{"worker": "system", "action": "replace_in_file", "args": {"path": ".env", "old": "TOKEN=xxxx", "new": "TOKEN=yyyy"}, "risk_level": "high"}

User: "在.env增加API_KEY=zzzz"
{"worker": "system", "action": "append_to_file", "args": {"path": ".env", "content": "\nAPI_KEY=zzzz"}, "risk_level": "medium"}
```

## 测试策略

### 单元测试 (`tests/test_system_worker.py`)

```python
# write_file
- test_write_file_creates_new_file
- test_write_file_overwrites_existing
- test_write_file_dry_run
- test_write_file_parent_not_exists
- test_write_file_permission_denied

# append_to_file
- test_append_to_file_success
- test_append_to_file_dry_run
- test_append_to_file_not_exists

# replace_in_file
- test_replace_in_file_exact_match
- test_replace_in_file_multiple_matches
- test_replace_in_file_with_count
- test_replace_in_file_regex
- test_replace_in_file_no_match
- test_replace_in_file_invalid_regex
- test_replace_in_file_dry_run
```

### 集成测试 (`tests/test_file_operations.py`)

```python
- test_create_env_file_workflow
- test_replace_env_value_workflow
- test_append_env_field_workflow
```

## 涉及文件

- `src/workers/system.py` - 新增 3 个 action 实现
- `src/orchestrator/prompt.py` - 更新能力描述和示例
- `tests/test_system_worker.py` - 单元测试
- `tests/test_file_operations.py` - 集成测试

## 设计决策

1. **扩展 SystemWorker** - 文件操作与现有 `delete_files` 同类，不新建 Worker
2. **纯文本通用** - 不做格式感知（.env/JSON/YAML），LLM 负责理解格式
3. **精确匹配优先** - 默认安全，`regex=True` 可选启用正则
4. **按操作类型区分风险** - 创建/追加为 medium，覆写/替换为 high
5. **不自动创建父目录** - 避免意外创建深层路径
6. **append 要求文件存在** - 区分"追加"和"创建"语义
