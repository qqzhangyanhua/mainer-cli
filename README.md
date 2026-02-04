# OpsAI Terminal Assistant

> 🤖 终端智能运维助手 - 通过自然语言实现运维自动化

OpsAI 是一个基于 LLM 的终端智能助手，采用 Orchestrator-Workers 架构，通过自然语言降低复杂运维任务的门槛。

## ✨ 特性

- **自然语言交互**: 用自然语言描述任务，AI 自动执行
- **双模交互**: CLI 模式快速执行，TUI 模式交互式会话
- **三层安全防护**: 危险模式检测 + 人工确认 + 审计日志
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

# TUI 模式 - 交互式会话
opsai-tui
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
│   ├── engine.py       # ReAct 循环
│   ├── safety.py       # 安全检查
│   └── prompt.py       # Prompt 模板
├── workers/            # 执行器
│   ├── base.py         # Worker 基类
│   ├── system.py       # 系统操作
│   └── audit.py        # 审计日志
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
- `SystemWorker`: 文件系统操作
- `AuditWorker`: 审计日志写入
- (未来) `ContainerWorker`: Docker 容器管理

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
    "tui_max_risk": "high"
  },
  "audit": {
    "log_path": "~/.opsai/audit.log",
    "max_log_size_mb": 100,
    "retain_days": 90
  }
}
```

## 📄 License

MIT License
