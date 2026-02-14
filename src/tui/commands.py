"""TUI 斜杠命令处理"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from rich.syntax import Syntax
from rich.table import Table

from src import __version__
from src.config.manager import ConfigManager
from src.orchestrator.scenarios import ScenarioManager
from src.tui.widgets import format_path, mask_secret
from src.types import ConversationEntry, HistoryWritable


def handle_slash_command(
    command_line: str,
    history: HistoryWritable,
    config_manager: ConfigManager,
    config: object,
    scenario_manager: ScenarioManager,
    session_history: list[ConversationEntry],
    status_enabled: bool,
    verbose_enabled: bool,
    app: object,
    set_status: object,
    update_status_bar: object,
    hide_slash_menu: object,
) -> tuple[bool, dict[str, object]]:
    """处理 TUI 斜杠命令，返回 (是否已处理, 状态更新字典)

    状态更新字典可能包含:
    - status_enabled: bool
    - verbose_enabled: bool
    - config: 新配置对象
    - exit: bool
    - clear: bool
    """
    # 此函数较复杂，保持在 OpsAIApp 中作为方法更合适
    # 这里仅提供场景相关的独立辅助函数
    raise NotImplementedError("Commands are handled inline in OpsAIApp")


def show_help(history: HistoryWritable) -> None:
    """展示帮助信息"""
    history.write("[bold green]可用命令[/bold green]")
    history.write("/help     - 显示帮助")
    history.write("/scenario - 查看运维场景（/scenario <id>）")
    history.write("/clear    - 清空当前对话（历史 + 上下文）")
    history.write("/config   - 显示当前配置（敏感字段已脱敏）")
    history.write("/history  - 显示会话历史摘要（/history [N|all]）")
    history.write("/pwd      - 显示当前目录")
    history.write("/export   - 导出会话记录（/export [json|md] [path]）")
    history.write("/theme    - 切换主题（/theme toggle|on|off）")
    history.write("/verbose  - 思考过程展示开关（/verbose on|off|toggle）")
    history.write("/status   - 状态栏开关（/status on|off|toggle）")
    history.write("/copy     - 复制输出（/copy all|N|mode）")
    history.write("/monitor  - 系统资源快照（CPU/内存/磁盘/负载）")
    history.write("/logs     - 日志分析（/logs <容器名> 或 /logs file <路径>）")
    history.write("/exit     - 退出")
    history.write("[dim]快捷键：Ctrl+C 退出，Ctrl+L 清空对话，Ctrl+Y 复制模式[/dim]")


def show_config(
    history: HistoryWritable,
    config_manager: ConfigManager,
) -> object:
    """展示当前配置（敏感字段脱敏），返回新配置对象或 None"""
    try:
        config = config_manager.load()
    except Exception as e:
        history.write(f"[red]读取配置失败：{e!s}[/red]")
        return None

    config_dict = config.model_dump()
    config_dict["llm"]["api_key"] = mask_secret(config_dict["llm"].get("api_key", ""))
    config_dict["http"]["github_token"] = mask_secret(config_dict["http"].get("github_token", ""))

    config_json = json.dumps(config_dict, ensure_ascii=False, indent=2)
    config_path = config_manager.get_config_path()

    history.write(f"[bold green]当前配置[/bold green]（{config_path}）")
    history.write(Syntax(config_json, "json", theme="ansi_dark", word_wrap=True))
    history.write("[dim]提示：敏感字段已脱敏显示[/dim]")
    return config


def show_history_summary(
    history: HistoryWritable,
    session_history: list[ConversationEntry],
    args: list[str] | None = None,
) -> None:
    """显示会话历史摘要

    支持参数:
      /history        显示最近 5 条
      /history <N>    显示最近 N 条
      /history all    显示全部
    """
    from src.tui.widgets import truncate_text

    total = len(session_history)
    if total == 0:
        history.write("[dim]暂无会话历史[/dim]")
        return

    show_count = 5
    if args:
        first = args[0].lower()
        if first == "all":
            show_count = total
        elif first.isdigit():
            show_count = max(1, int(first))
        else:
            history.write("[yellow]用法：/history [N|all][/yellow]")
            return

    recent = session_history[-show_count:]
    shown = len(recent)
    history.write(f"[bold green]会话历史[/bold green] 共 {total} 条，显示最近 {shown} 条")
    start_index = total - shown + 1
    for offset, entry in enumerate(recent):
        index = start_index + offset
        user_text = truncate_text(entry.user_input or "", 60)
        result_text = truncate_text(entry.result.message, 60)
        history.write(f"{index}. 用户: {user_text}")
        history.write(f"[dim]   结果: {result_text}[/dim]")


def show_scenarios(
    history: HistoryWritable,
    scenario_manager: ScenarioManager,
) -> None:
    """显示所有场景列表"""
    categories = {
        "troubleshooting": "🔴 故障排查",
        "maintenance": "🛠️  日常维护",
        "deployment": "🚀 项目部署",
        "monitoring": "📊 监控查看",
    }

    history.write("[bold green]═══ 常见运维场景 ═══[/bold green]")

    for cat_id, cat_name in categories.items():
        cat_scenarios = scenario_manager.get_by_category(cat_id)
        if not cat_scenarios:
            continue

        history.write(f"\n[bold]{cat_name}[/bold]")
        for scenario in cat_scenarios:
            risk_badge = {
                "safe": "[green]🟢[/green]",
                "medium": "[yellow]🟡[/yellow]",
                "high": "[red]🔴[/red]",
            }.get(scenario.risk_level, "")

            history.write(f"  {scenario.icon} [{scenario.id}] {scenario.title} {risk_badge}")
            history.write(f"      [dim]{scenario.description}[/dim]")

    history.write("")
    history.write("[dim]💡 使用方法：[/dim]")
    history.write("[dim]   - 输入 /scenario <ID> 查看详情（如 '/scenario disk_full'）[/dim]")
    history.write("[dim]   - 或直接描述你的问题（如 '服务打不开'）[/dim]")


def handle_scenario_command(
    args: list[str],
    history: HistoryWritable,
    scenario_manager: ScenarioManager,
) -> None:
    """处理场景命令"""
    if not args:
        show_scenarios(history, scenario_manager)
        return

    first_arg = args[0].lower()

    if first_arg == "search" and len(args) > 1:
        keyword = " ".join(args[1:])
        results = scenario_manager.search(keyword)
        if results:
            history.write(f"[bold green]搜索结果：{keyword}[/bold green]")
            for s in results:
                history.write(f"  {s.icon} [{s.id}] {s.title}")
                history.write(f"      {s.description}")
        else:
            history.write(f"[yellow]未找到匹配的场景：{keyword}[/yellow]")
        return

    scenario = scenario_manager.get_by_id(first_arg)
    if not scenario:
        results = scenario_manager.search(first_arg)
        if results:
            history.write(f"[yellow]未找到场景 '{first_arg}'，你是否想要：[/yellow]")
            for s in results[:3]:
                history.write(f"  {s.icon} [{s.id}] {s.title}")
        else:
            history.write(f"[yellow]未找到场景：{first_arg}[/yellow]")
            history.write("[dim]输入 /scenario 查看所有可用场景[/dim]")
        return

    risk_badge = {
        "safe": "[green][安全][/green]",
        "medium": "[yellow][中等风险][/yellow]",
        "high": "[red][高危][/red]",
    }.get(scenario.risk_level, "")

    history.write(f"[bold green]{scenario.icon} {scenario.title}[/bold green] {risk_badge}")
    history.write(f"[dim]{scenario.description}[/dim]")
    history.write("")
    history.write("[bold]执行步骤：[/bold]")
    for i, step in enumerate(scenario.steps, 1):
        history.write(f"  {i}. {step.description}")
        history.write(f"     [cyan]> {step.prompt}[/cyan]")
    history.write("")
    history.write("[dim]提示：输入上述命令或直接描述你的需求[/dim]")


def export_history(
    args: list[str],
    history: HistoryWritable,
    session_history: list[ConversationEntry],
    config_model: str,
) -> None:
    """导出会话记录"""
    export_format = "json"
    export_path: Path | None = None

    if args:
        first = args[0].lower()
        if first in {"json", "md", "markdown"}:
            export_format = "md" if first in {"md", "markdown"} else "json"
            if len(args) > 1:
                export_path = Path(args[1]).expanduser()
        else:
            export_path = Path(args[0]).expanduser()
            if export_path.suffix.lower() == ".md":
                export_format = "md"
            else:
                export_format = "json"

    if export_path is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"opsai-history-{timestamp}.{export_format}"
        export_path = Path.cwd() / filename

    export_data = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "model": config_model,
        "cwd": str(Path.cwd()),
        "entries": [entry.model_dump() for entry in session_history],
    }

    try:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        if export_format == "md":
            content = _render_history_markdown(export_data)
            export_path.write_text(content, encoding="utf-8")
        else:
            export_path.write_text(
                json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception as e:
        history.write(f"[red]导出失败：{e!s}[/red]")
        return

    history.write(f"[green]已导出会话记录：{format_path(export_path)}[/green]")


def _render_history_markdown(export_data: dict[str, object]) -> str:
    """渲染 Markdown 导出内容"""
    lines: list[str] = []
    lines.append("# OpsAI 会话导出")
    lines.append("")
    lines.append(f"- 导出时间: {export_data.get('exported_at')}")
    lines.append(f"- 版本: {export_data.get('version')}")
    lines.append(f"- 模型: {export_data.get('model')}")
    lines.append(f"- 目录: {export_data.get('cwd')}")
    lines.append("")

    entries = export_data.get("entries", [])
    if isinstance(entries, list) and entries:
        for index, entry in enumerate(entries, start=1):
            lines.append(f"## 记录 {index}")
            user_input = ""
            instruction = ""
            result_message = ""
            if isinstance(entry, dict):
                user_input = str(entry.get("user_input") or "")
                instruction_obj = entry.get("instruction") or {}
                if isinstance(instruction_obj, dict):
                    worker = instruction_obj.get("worker", "")
                    action = instruction_obj.get("action", "")
                    inst_args = instruction_obj.get("args", {})
                    instruction = f"{worker}.{action} {inst_args}"
                result_obj = entry.get("result") or {}
                if isinstance(result_obj, dict):
                    result_message = str(result_obj.get("message", ""))
            lines.append(f"- 用户输入: {user_input}")
            lines.append(f"- 指令: {instruction}")
            lines.append(f"- 结果: {result_message}")
            lines.append("")
    else:
        lines.append("暂无会话记录")
        lines.append("")

    return "\n".join(lines)


def show_monitor_snapshot(history: HistoryWritable) -> None:
    """直接执行 monitor.snapshot 并以 Rich 表格展示结果"""
    from src.workers.monitor import MonitorWorker

    worker = MonitorWorker()

    try:
        result = asyncio.get_event_loop().run_until_complete(
            worker.execute("snapshot", {})
        )
    except RuntimeError:
        # 已在 async 上下文中，用 asyncio.run 的替代方案
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = pool.submit(
                asyncio.run, worker.execute("snapshot", {})
            ).result()

    if not result.success or not isinstance(result.data, list):
        history.write(f"[red]监控快照失败: {result.message}[/red]")
        return

    status_style: dict[str, str] = {
        "ok": "green",
        "warning": "yellow",
        "critical": "red",
    }

    table = Table(title="系统资源快照", expand=True)
    table.add_column("指标", style="cyan", no_wrap=True)
    table.add_column("状态", justify="center")
    table.add_column("详情")

    for item in result.data:
        status = str(item.get("status", "ok"))
        color = status_style.get(status, "white")
        status_label = f"[{color}]{status.upper()}[/{color}]"
        table.add_row(
            str(item.get("name", "")),
            status_label,
            str(item.get("message", "")),
        )

    history.write(table)
    history.write(f"[dim]{result.message}[/dim]")


def show_log_analysis(
    args: list[str],
    history: HistoryWritable,
) -> None:
    """执行日志分析并展示结果

    用法:
      /logs <container>           分析容器日志
      /logs file <path>           分析日志文件
      /logs <container> --tail N  指定日志行数
    """
    import asyncio
    import concurrent.futures

    from rich.table import Table

    from src.workers.log_analyzer import LogAnalyzerWorker

    if not args:
        history.write("[yellow]用法: /logs <容器名> 或 /logs file <路径>[/yellow]")
        history.write("[dim]  /logs nginx              分析 nginx 容器日志[/dim]")
        history.write("[dim]  /logs nginx --tail 1000  最近 1000 行[/dim]")
        history.write("[dim]  /logs file /var/log/syslog  分析日志文件[/dim]")
        return

    worker = LogAnalyzerWorker()

    # 解析参数
    action = "analyze_container"
    worker_args: dict[str, str | int] = {}
    tail_n = 500

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "file" and i + 1 < len(args):
            action = "analyze_file"
            worker_args["path"] = args[i + 1]
            i += 2
            continue
        if arg == "--tail" and i + 1 < len(args):
            try:
                tail_n = int(args[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if "container" not in worker_args and action == "analyze_container":
            worker_args["container"] = arg
        i += 1

    worker_args["tail"] = tail_n

    try:
        result = asyncio.get_event_loop().run_until_complete(
            worker.execute(action, worker_args)  # type: ignore[arg-type]
        )
    except RuntimeError:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = pool.submit(
                asyncio.run, worker.execute(action, worker_args)  # type: ignore[arg-type]
            ).result()

    if not result.success:
        history.write(f"[red]日志分析失败: {result.message}[/red]")
        return

    # 展示结果
    history.write(f"[bold green]{result.message.split(chr(10))[0]}[/bold green]")

    if isinstance(result.data, list) and result.data:
        # 级别分布表
        level_rows = [r for r in result.data if isinstance(r, dict) and str(r.get("name", "")).startswith("level_")]
        if level_rows:
            level_table = Table(title="级别分布", expand=False)
            level_table.add_column("级别", style="cyan")
            level_table.add_column("数量", justify="right")

            level_style_map: dict[str, str] = {
                "FATAL": "red bold",
                "ERROR": "red",
                "WARN": "yellow",
                "INFO": "green",
                "DEBUG": "dim",
            }

            for row in level_rows:
                level_name = str(row.get("name", ""))[6:]  # strip "level_"
                count = str(row.get("count", 0))
                style = level_style_map.get(level_name, "white")
                level_table.add_row(f"[{style}]{level_name}[/{style}]", count)

            history.write(level_table)

        # 错误模式表
        error_rows = [r for r in result.data if isinstance(r, dict) and str(r.get("name", "")).startswith("error_")]
        if error_rows:
            error_table = Table(title="Top 错误模式", expand=True)
            error_table.add_column("#", style="dim", width=3)
            error_table.add_column("次数", justify="right", style="red", width=6)
            error_table.add_column("模式")

            for idx, row in enumerate(error_rows[:10], 1):
                error_table.add_row(
                    str(idx),
                    str(row.get("count", 0)),
                    str(row.get("pattern", ""))[:80],
                )
            history.write(error_table)

    # 显示详细摘要
    for line in result.message.split("\n")[1:]:
        if line.strip():
            history.write(f"[dim]{line}[/dim]")
