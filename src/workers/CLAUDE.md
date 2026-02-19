[根目录](../../CLAUDE.md) > [src](../) > **workers**

# workers 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

Worker 执行器集合。所有 Worker 保持"愚蠢"状态，仅负责执行具体操作，不做推理决策。通过 `BaseWorker` 抽象基类统一接口，支持自文档化（`description` + `get_actions()` 自动生成 Prompt 工具描述和 Function Calling schema）。

## 入口与启动

- **`base.py`** -- `BaseWorker` 抽象基类，定义 `name`, `description`, `get_capabilities()`, `get_actions()`, `get_tool_schema()`, `execute()` 接口。
- Worker 实例在 `orchestrator/engine.py` 的 `__init__` 中按需注册（try/except 模式，缺少可选依赖时跳过）。

## 对外接口

每个 Worker 通过 `execute(action, args)` 暴露能力:

| Worker | 主要 Actions | 说明 |
|--------|-------------|------|
| `system` | list_files, find_large_files, check_disk_usage, delete_files, write_file, append_to_file, replace_in_file | 文件系统操作 |
| `shell` | execute_command | 白名单化 Shell 命令执行 |
| `container` | list_containers, inspect_container, logs, restart, stop, start, stats | Docker 容器管理（基于 shell 命令，无需 docker-py） |
| `compose` | status, health, logs, restart, up, down | Docker Compose 管理 |
| `deploy` | deploy | GitHub 项目一键部署（LLM 驱动） |
| `analyze` | explain | 智能分析运维对象（Docker/进程/端口等） |
| `monitor` | snapshot, check_port, check_http, check_process, top_processes, find_service_port | 系统资源监控（只读） |
| `log_analyzer` | analyze_lines, analyze_file, analyze_container | 日志分析（模式聚合、趋势） |
| `http` | fetch_url, fetch_github_readme, list_github_files | HTTP 请求 |
| `git` | clone, pull, status | Git 操作 |
| `audit` | log_operation | 审计日志记录 |
| `chat` | respond | 最终中文回复（仅用于 is_final=true） |
| `kubernetes` | get, describe, logs, top, rollout, scale | Kubernetes 管理 |
| `remote` | execute, list_hosts, test_connection | SSH 远程执行（需 asyncssh） |
| `notifier` | (webhook/desktop 通知) | 告警通知 |
| `file_ops` | (辅助模块) | write_file/append_to_file/replace_in_file 的底层实现 |

## 关键依赖与配置

- `psutil`: MonitorWorker 系统资源采集
- `httpx`: HttpWorker HTTP 请求
- `asyncssh` (可选): RemoteWorker SSH 连接
- `pyperclip` (可选): TUI 剪贴板支持
- Shell 命令安全: 所有 shell 命令经 `PolicyEngine` 白名单校验

## 数据模型

- `WorkerResult`: 统一返回格式（success, data, message, task_completed, simulated）
- `ToolAction` + `ActionParam`: Worker 自文档化 schema
- `AnalyzeTarget` / `AnalyzeTargetType`: 分析对象类型
- `MonitorMetric` / `MonitorStatus`: 监控指标
- `LogAnalysis` / `LogEntry` / `LogPatternCount`: 日志分析结果
- `deploy/types.py`: 部署回调类型定义

## 子模块: deploy/

```
workers/deploy/
  __init__.py
  worker.py      # DeployWorker 主入口
  planner.py     # LLM 驱动的部署计划生成
  executor.py    # 部署命令执行
  diagnose.py    # 错误诊断与自动重试
  types.py       # 回调类型定义
```

## 测试与质量

相关测试文件 (20+):
- `tests/test_workers_base.py`, `tests/test_workers_system.py`, `tests/test_workers_shell.py`
- `tests/test_container_worker.py`, `tests/test_compose.py`
- `tests/test_deploy_worker.py`, `tests/test_deploy_executor.py`, `tests/test_deploy_integration.py`
- `tests/test_deploy_intent.py`, `tests/test_deploy_project_type.py`, `tests/test_deploy_verification.py`
- `tests/test_analyze_worker.py`, `tests/test_analyze_integration.py`
- `tests/test_monitor_worker.py`, `tests/test_http_worker.py`
- `tests/test_log_analyzer.py`, `tests/test_notifier.py`
- `tests/test_remote.py`, `tests/test_kubernetes.py`
- `tests/test_file_operations.py`, `tests/test_path_utils.py`

## 常见问题 (FAQ)

**Q: 如何添加新 Worker?**
A: 继承 `BaseWorker`，实现 `name`, `description`, `get_capabilities()`, `get_actions()`, `execute()`。在 `engine.py.__init__` 中注册。Prompt 工具描述自动生成。

**Q: ContainerWorker 为什么不用 docker-py?**
A: 减少 50MB 依赖体积，基于 shell 命令实现，与 Docker CLI 行为一致。

**Q: Shell 命令的安全校验在哪?**
A: `ShellWorker` 内部调用 `PolicyEngine` 进行白名单校验。阻止 `;`, `$()`, 反引号, `> file` 重定向。

## 相关文件清单

- `src/workers/base.py`
- `src/workers/system.py`
- `src/workers/shell.py`
- `src/workers/container.py`
- `src/workers/compose.py`
- `src/workers/analyze.py`
- `src/workers/analyze_cache.py`
- `src/workers/monitor.py`
- `src/workers/log_analyzer.py`
- `src/workers/http.py`
- `src/workers/git.py`
- `src/workers/audit.py`
- `src/workers/chat.py`
- `src/workers/kubernetes.py`
- `src/workers/remote.py`
- `src/workers/notifier.py`
- `src/workers/file_ops.py`
- `src/workers/path_utils.py`
- `src/workers/deploy/worker.py`
- `src/workers/deploy/planner.py`
- `src/workers/deploy/executor.py`
- `src/workers/deploy/diagnose.py`
- `src/workers/deploy/types.py`
