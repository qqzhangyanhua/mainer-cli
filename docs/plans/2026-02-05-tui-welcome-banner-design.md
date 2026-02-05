# TUI 启动欢迎画面设计

## 概述

为 OpsAI TUI 模式添加启动欢迎画面，解决当前进入 TUI 后一片空白的问题。

## 目标

- 每次启动 TUI 时显示简洁的欢迎画面
- 包含 ASCII Logo、版本号、LLM 模型、工作目录
- 风格参考 Claude Code 的启动画面

## 设计

### ASCII Logo

```
   ▄▄▄▄▄▄▄
   █ ●  ● █
   █  ▀▀  █
   ▀▀█▀█▀▀
```

像素块风格机器人头像，强调 AI 助手身份。

### 完整布局

```
   ▄▄▄▄▄▄▄
   █ ●  ● █      OpsAI v0.1.0
   █  ▀▀  █      LLM: qwen2.5:7b
   ▀▀█▀█▀▀       ~/AI/mainer-cli
```

### 信息来源

| 信息 | 来源 |
|------|------|
| 版本号 | `src/__init__.py` 的 `__version__` |
| LLM 模型 | `self._config.llm.model` |
| 工作目录 | `Path.cwd()`，home 目录用 `~` 缩写 |

### 颜色方案

- Logo: 绿色（`[green]`）
- 版本号: 加粗（`[bold]`）
- 其他信息: 柔和灰色（`[dim]`）

## 实现

### 修改文件

`src/tui.py`

### 修改点

1. **`on_mount()` 方法** - 添加 `_show_welcome_banner()` 调用

```python
def on_mount(self) -> None:
    self._update_status_bar()
    input_widget = self.query_one("#user-input", Input)
    input_widget.suggester = SlashCommandSuggester(self._get_slash_suggestion)

    # 始终显示启动画面
    self._show_welcome_banner()

    # 首次运行额外显示环境检测向导
    if self._is_first_run():
        self._show_welcome_wizard()
```

2. **新增 `_show_welcome_banner()` 方法**

```python
def _show_welcome_banner(self) -> None:
    """显示启动欢迎画面"""
    history = self.query_one("#history", RichLog)

    # 获取信息
    version = __version__
    model = self._config.llm.model
    cwd = str(Path.cwd()).replace(str(Path.home()), "~")

    # ASCII Logo + 信息
    banner = f"""[green]   ▄▄▄▄▄▄▄[/green]
[green]   █ ●  ● █[/green]      [bold]OpsAI[/bold] v{version}
[green]   █  ▀▀  █[/green]      [dim]LLM: {model}[/dim]
[green]   ▀▀█▀█▀▀[/green]       [dim]{cwd}[/dim]
"""
    history.write(banner)
```

## 测试

- 运行 `uv run opsai-tui` 验证启动画面显示
- 验证首次运行时 banner + wizard 都显示
- 验证非首次运行时只显示 banner

## 影响范围

- 仅修改 `src/tui.py`
- 不影响现有功能
- 向后兼容
