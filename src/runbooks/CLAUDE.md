[根目录](../../CLAUDE.md) > [src](../) > **runbooks**

# runbooks 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

YAML 格式的诊断手册（Runbook）加载与匹配。根据用户输入关键词匹配相关的诊断流程，注入到 LLM Prompt 中作为参考（不强制执行，让 LLM 自适应）。

## 入口与启动

- **`loader.py`** -- `RunbookLoader` 类，延迟加载所有 Runbook YAML，提供关键词匹配。
- **`data/`** -- YAML Runbook 文件目录。

## 对外接口

| 方法 | 说明 |
|------|------|
| `RunbookLoader.match(user_input, top_k)` | 根据用户输入匹配相关 Runbook |
| `DiagnosticRunbook.to_prompt_context()` | 转换为 Prompt 可注入的文本 |

## 数据模型

- `DiagnosticRunbook`: 诊断手册（name, description, keywords, steps）
- `DiagnosticStep`: 诊断步骤（description, command, risk）

## 预置 Runbook

| 文件 | 场景 |
|------|------|
| `service_health.yaml` | 服务健康检查 |
| `container_troubleshoot.yaml` | 容器故障排查 |
| `performance.yaml` | 性能问题诊断 |
| `disk_cleanup.yaml` | 磁盘清理 |
| `network_troubleshoot.yaml` | 网络问题排查 |
| `log_analysis.yaml` | 日志分析 |

## 测试与质量

- `tests/test_runbook.py`

## 相关文件清单

- `src/runbooks/__init__.py`
- `src/runbooks/loader.py`
- `src/runbooks/data/service_health.yaml`
- `src/runbooks/data/container_troubleshoot.yaml`
- `src/runbooks/data/performance.yaml`
- `src/runbooks/data/disk_cleanup.yaml`
- `src/runbooks/data/network_troubleshoot.yaml`
- `src/runbooks/data/log_analysis.yaml`
