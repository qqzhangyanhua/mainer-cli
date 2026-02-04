# OpsAI Terminal Assistant

> 🤖 终端智能运维助手 - 通过自然语言实现运维自动化

OpsAI 是一个基于 LLM 的终端智能助手，采用 Orchestrator-Workers 架构，通过自然语言降低复杂运维任务的门槛。

## ✨ 特性

- **自然语言交互**: 用自然语言描述任务，AI 自动执行
- **双模交互**: CLI 模式快速执行，TUI 模式交互式会话
- **三层安全防护**: 危险模式检测 + 人工确认 + 审计日志
- **Dry-run 模式**: 模拟执行，预览操作而不实际执行
- **容器管理**: 原生支持 Docker 容器操作
- **任务模板**: 预定义的多步骤运维流程，开箱即用
- **多 LLM 支持**: 通过 LiteLLM 支持 Ollama、OpenAI、Claude 等
- **ReAct 循环**: 智能多步任务编排

## 🚀 快速开始

### 安装

```bash
# 使用 pip
pip install opsai

# 或使用 uv
uv tool install opsai
```

### 基本使用

```bash
# CLI 模式 - 快速查询
opsai query "检查磁盘使用情况"
opsai query "查找 /var/log 下大于 100MB 的文件"

# Dry-run 模式 - 预览操作
opsai query "删除临时文件" --dry-run

# TUI 模式 - 交互式会话
opsai-tui
```

### 容器管理

```bash
# 列出所有运行中的容器
opsai query "列出所有容器"

# 查看容器状态
opsai query "查看容器 my-app 的状态"

# 重启容器（需要 TUI 确认）
opsai query "重启容器 my-app"
```

### 任务模板

```bash
# 列出所有可用模板
opsai template list

# 查看模板详情
opsai template show disk_cleanup

# 运行模板
opsai template run disk_cleanup

# Dry-run 模式运行模板
opsai template run disk_cleanup --dry-run

# 带上下文变量运行模板
opsai template run service_restart --context '{"container_id": "my-app"}'
```

### 配置 LLM

```bash
# 查看当前配置
opsai config show

# 配置 OpenAI
opsai config set-llm --model gpt-4o --api-key sk-xxx

# 配置本地 Ollama
opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1
```
# 配置文件存储在 `~/.opsai/config.json`

## 🔒 安全机制

OpsAI 采用三层安全防护：

1. **危险模式检测**: 自动识别 `rm -rf`、`kill -9` 等危险命令
2. **人工确认**: 高危操作必须通过 TUI 模式确认
3. **审计日志**: 所有操作记录到 `~/.opsai/audit.log`

### 风险等级

| 等级 | 描述 | CLI 模式 | TUI 模式 |
|------|------|----------|----------|
| safe | 只读操作 | ✅ 自动执行 | ✅ 自动执行 |
| medium | 可修改操作 | ❌ 拒绝 | ⚠️ 需确认 |
| high | 破坏性操作 | ❌ 拒绝 | ⚠️ 需确认 |

## 📁 项目结构

```
src/
├── cli.py              # CLI 入口
├── tui.py              # TUI 入口
├── orchestrator/       # 编排器
│   ├── engine.py       # ReAct 循环（支持 dry-run）
│   ├── safety.py       # 安全检查
│   └── prompt.py       # Prompt 模板
├── workers/            # 执行器
│   ├── base.py         # Worker 基类
│   ├── system.py       # 系统操作（支持 dry-run）
│   ├── container.py    # 容器管理（Docker）
│   └── audit.py        # 审计日志
├── templates/          # 任务模板系统
│   └── manager.py      # 模板管理器
├── config/             # 配置管理
├── context/            # 环境上下文
├── llm/                # LLM 客户端
└── types.py            # 类型定义
```

## 🛠️ 开发

```bash
# 克隆仓库
git clone https://github.com/yourusername/opsai.git
cd opsai

# 安装依赖
uv sync

# 运行测试
uv run pytest

# 类型检查
uv run mypy src/

# 代码格式化
uv run ruff format src/ tests/
```

## 🏗️ 架构

```
用户输入 → Orchestrator (LLM 引擎) → Worker Pool → 系统调用
         ↑                             ↓
         └──────── ReAct 循环 ──────────┘
```

### Orchestrator 职责
- 接收用户自然语言指令
- 调用 LLM 生成结构化 JSON 指令
- 执行安全检查
- 实现 ReAct 循环

### Worker Pool 职责
- `SystemWorker`: 文件系统操作（支持 dry-run）
  - 查找大文件、检查磁盘使用、删除文件
- `ContainerWorker`: Docker 容器管理（支持 dry-run）
  - 列出容器、查看状态、日志查询、启动/停止/重启
- `AuditWorker`: 审计日志写入

## 📝 配置文件

配置文件位于 `~/.opsai/config.json`:

```json
{
  "llm": {
    "base_url": "http://localhost:11434/v1",
    "model": "qwen2.5:7b",
    "api_key": "",
    "timeout": 30,
    "max_tokens": 2048
  },
  "safety": {
    "auto_approve_safe": true,
    "cli_max_risk": "safe",
    "tui_max_risk": "high",
    "dry_run_by_default": false,
    "require_dry_run_for_high_risk": true
  },
  "audit": {
    "log_path": "~/.opsai/audit.log",
    "max_log_size_mb": 100,
    "retain_days": 90
  }
}
```

### 新增配置说明

- **safety.dry_run_by_default**: 默认启用 dry-run 模式（推荐生产环境设为 true）
- **safety.require_dry_run_for_high_risk**: 高风险操作强制先 dry-run（推荐保持 true）

## 📄 License

MIT License
