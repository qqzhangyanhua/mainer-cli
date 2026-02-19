[根目录](../../CLAUDE.md) > [src](../) > **config**

# config 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

Pydantic 配置模型管理。定义 OpsAI 所有配置项的类型与默认值，提供 JSON 文件读写。

## 入口与启动

- **`manager.py`** -- `ConfigManager` 类（加载/保存配置）和 `OpsAIConfig` Pydantic 模型。

## 对外接口

| 类 | 说明 |
|----|------|
| `OpsAIConfig` | 完整配置模型，包含 llm/safety/audit/http/tui/monitor/notifications/remote 子配置 |
| `ConfigManager` | 配置文件管理器，`load()` 加载或创建默认配置，`save()` 保存 |
| `LLMConfig` | LLM 配置（base_url, model, api_key, timeout, max_tokens, temperature, supports_function_calling, context_window） |
| `SafetyConfig` | 安全配置（auto_approve_safe, cli_max_risk, tui_max_risk, dry_run_by_default, require_dry_run_for_high_risk） |
| `MonitorConfig` | 监控阈值配置（cpu/memory/disk warning/critical） |
| `RemoteConfig` | 远程主机配置（hosts, default_key_path, connect_timeout, command_timeout） |

## 数据模型

配置文件路径: `~/.opsai/config.json`

所有配置类继承 `pydantic.BaseModel`，字段含 `Field(default=..., description=...)` 描述。

## 测试与质量

- `tests/test_config.py`

## 相关文件清单

- `src/config/__init__.py`
- `src/config/manager.py`
