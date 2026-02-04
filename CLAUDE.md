# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpsAI 是一个基于 LLM 的终端智能运维助手，采用 Orchestrator-Workers 架构，通过自然语言实现运维自动化。

## Development Commands

### Setup
```bash
# 安装依赖
uv sync

# 安装为可执行工具
uv tool install .
```

### Testing
```bash
# 运行所有测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_container_worker.py

# 运行带覆盖率的测试
uv run pytest --cov=src --cov-report=term-missing
```

### Code Quality
```bash
# 类型检查
uv run mypy src/

# 代码格式化
uv run ruff format src/ tests/

# Linting
uv run ruff check src/ tests/
```

### Running the Application
```bash
# CLI 模式快速查询
uv run opsai query "检查磁盘使用情况"

# Dry-run 模式（预览操作，不实际执行）
uv run opsai query "删除临时文件" --dry-run

# TUI 模式交互式会话
uv run opsai-tui

# 配置管理
uv run opsai config show
uv run opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1

# 任务模板
uv run opsai template list
uv run opsai template run disk_cleanup --dry-run
```

## Architecture

### 核心设计理念：Orchestrator-Workers 分离

**Orchestrator (src/orchestrator/)** - 负责推理和决策：
- `engine.py`: 实现 ReAct (Reason-Act) 循环，协调整个执行流程
- `prompt.py`: 管理 LLM Prompt 模板，定义 Worker 能力
- `safety.py`: 三层安全防护（危险模式检测 + 人工确认 + 审计日志）

**Workers (src/workers/)** - 保持"愚蠢"状态，仅负责执行：
- `base.py`: Worker 抽象基类，定义统一接口
- `system.py`: 系统操作（文件查找、磁盘检查、文件删除）
- `container.py`: Docker 容器管理（列出、重启、日志查看）
- `audit.py`: 审计日志记录

### ReAct 循环流程

```
用户输入 → Orchestrator.react_loop()
         ↓
    1. Reason: LLM 生成 Instruction JSON
         ↓
    2. Safety Check: 风险等级评估
         ↓
    3. Act: 执行对应 Worker
         ↓
    4. 判断 task_completed
         ↓
    (循环直到完成或达到最大迭代次数)
```

### 关键类型定义 (src/types.py)

**严格禁止 `any` 类型** - 所有类型定义必须显式指定：

- `Instruction`: Orchestrator → Worker 的指令格式
  - `worker`: 目标 Worker 名称
  - `action`: 动作名称
  - `args`: 参数字典（类型为 `dict[str, ArgValue]`）
  - `risk_level`: "safe" | "medium" | "high"
  - `dry_run`: 是否模拟执行

- `WorkerResult`: Worker → Orchestrator 的结果格式
  - `success`: 执行是否成功
  - `data`: 结构化数据（可选）
  - `message`: 人类可读描述
  - `task_completed`: 任务是否完成（决定循环是否继续）
  - `simulated`: 是否为 dry-run 结果

- `ConversationEntry`: ReAct 循环的对话历史记录

### Dry-run 模式实现

所有支持 dry-run 的 Worker 必须：
1. 在 `args` 中接受 `dry_run: bool` 参数
2. 如果 `dry_run=True`，模拟执行并返回 `simulated=True` 的结果
3. 在 message 中明确标注 "[DRY-RUN]" 前缀

Orchestrator 会自动注入 dry_run 参数（engine.py:90-91）。

### 安全机制

风险等级决策规则 (orchestrator/safety.py):
- `safe`: 只读操作（如 ls, df, docker ps）→ CLI/TUI 自动执行
- `medium`: 可修改操作（如 touch, mkdir）→ TUI 需确认，CLI 拒绝
- `high`: 破坏性操作（如 rm -rf, kill -9）→ TUI 需确认，CLI 拒绝

## Adding New Workers

1. 继承 `BaseWorker` (src/workers/base.py)
2. 实现三个方法：
   - `name`: 返回 Worker 标识符
   - `get_capabilities()`: 返回支持的 action 列表
   - `execute(action, args)`: 实现具体逻辑
3. 在 `orchestrator/prompt.py` 的 `WORKER_CAPABILITIES` 中注册能力
4. 在 `orchestrator/engine.py` 的 `__init__` 中注册 Worker 实例

参考 `src/workers/container.py` 的实现模式。

## Configuration

配置文件位于 `~/.opsai/config.json`：
- `llm`: LLM 配置（model, base_url, api_key, timeout, max_tokens）
- `safety`: 安全配置（auto_approve_safe, cli_max_risk, dry_run_by_default）
- `audit`: 审计日志配置（log_path, max_log_size_mb, retain_days）

通过 `src/config/manager.py` 的 `OpsAIConfig` Pydantic 模型管理。

## Code Style Requirements

- Python 3.9+ 兼容性（使用 `Union` 而非 `|` 语法）
- 严格类型检查：`mypy --strict`，禁止 `any` 类型
- 行长度限制：100 字符
- 所有类型定义必须放在 `src/types.py`（单个文件超过 500 行需拆分）
- 使用 `from __future__ import annotations` 启用延迟注解
- 异步函数使用 `async def`，返回类型必须显式标注

## Testing Strategy

- 单元测试：测试单个 Worker 的 action 实现
- 集成测试：测试 Orchestrator 与 Worker 的交互
- Dry-run 测试：验证所有破坏性操作的模拟执行逻辑
- 使用 `pytest-asyncio` 处理异步测试

示例测试文件：
- `tests/test_container_worker.py`: ContainerWorker 单元测试
- `tests/test_dry_run.py`: Dry-run 模式集成测试
