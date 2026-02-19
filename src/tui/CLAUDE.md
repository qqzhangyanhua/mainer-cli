[根目录](../../CLAUDE.md) > [src](../) > **tui**

# tui 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

基于 Textual 框架的终端交互界面（TUI），提供交互式会话、健康仪表盘、斜杠命令、确认弹窗等功能。

## 入口与启动

- **`app.py`** -- `OpsAIApp(App[str])` 类，TUI 主应用。通过 `opsai-tui` 命令启动（`pyproject.toml` 中注册 `src.tui:main`）。
- **`__init__.py`** -- 导出 `main()` 入口函数。

## 对外接口

| 组件 | 说明 |
|------|------|
| `OpsAIApp` | 主应用，管理会话、输入、输出、键绑定 |
| `ConfirmationScreen` | 高危操作确认弹窗 |
| `SuggestedCommandScreen` | 权限错误建议命令弹窗 |
| `UserChoiceScreen` | 用户选择弹窗 |
| `HealthDashboard` | 健康仪表盘 Screen（实时系统监控面板） |
| `SlashCommandSuggester` | 斜杠命令自动补全 |
| `HistoryWriter` | 历史记录写入器 |

## 关键依赖与配置

- `textual>=0.47.0`: TUI 框架
- `rich>=13.0.0`: 富文本渲染
- `pyperclip` (可选): 剪贴板支持
- 配置项: `OpsAIConfig.tui.show_thinking`（是否展示思考过程）

## 测试与质量

- `tests/test_tui.py`
- `tests/test_dashboard.py`

## 相关文件清单

- `src/tui/__init__.py`
- `src/tui/app.py`
- `src/tui/screens.py`
- `src/tui/widgets.py`
- `src/tui/commands.py`
- `src/tui/dashboard.py`
