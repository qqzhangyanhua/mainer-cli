[根目录](../../CLAUDE.md) > [src](../) > **context**

# context 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

环境上下文采集、会话记忆持久化、变更追踪与回滚。为 Orchestrator 提供环境感知和跨会话记忆能力。

## 入口与启动

- **`environment.py`** -- `EnvironmentContext` dataclass，启动时采集一次 OS/Shell/Docker/CWD 等环境信息。
- **`memory.py`** -- `SessionMemory` 类，跨会话记忆管理器（`~/.opsai/memory.json`）。
- **`detector.py`** -- `EnvironmentDetector` 类，首次运行时检测环境生成个性化建议。
- **`change_tracker.py`** -- `ChangeTracker` 类，操作快照与回滚。

## 对外接口

| 组件 | 说明 |
|------|------|
| `EnvironmentContext.to_prompt_context()` | 生成环境信息 Prompt 片段 |
| `SessionMemory.store(key, value, category)` | 存储记忆 |
| `SessionMemory.recall(query)` | 检索相关记忆 |
| `EnvironmentDetector.detect()` | 检测环境信息 |
| `ChangeTracker.record(change)` | 记录变更 |
| `ChangeTracker.rollback(change_id)` | 回滚变更 |

## 数据模型

- `EnvironmentContext`: 环境上下文（os_type, os_version, shell, cwd, user, docker_available, timestamp）
- `EnvironmentInfo`: 详细环境信息（has_docker, docker_containers, has_systemd, has_kubernetes, disk_usage, memory_usage）
- `MemoryEntry`: 单条记忆（key, value, category, created_at, hit_count）
- `ChangeRecord`: 变更记录（change_type, file_path, backup_path, rollback_available）

## 测试与质量

- `tests/test_context.py`
- `tests/test_memory.py`
- `tests/test_change_tracker.py`
- `tests/test_detector.py`

## 相关文件清单

- `src/context/__init__.py`
- `src/context/environment.py`
- `src/context/memory.py`
- `src/context/detector.py`
- `src/context/change_tracker.py`
