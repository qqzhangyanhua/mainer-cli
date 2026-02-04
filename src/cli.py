"""OpsAI CLI 入口"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from src import __version__
from src.config.manager import ConfigManager
from src.orchestrator.engine import OrchestratorEngine
from src.templates import TemplateManager


app = typer.Typer(
    name="opsai",
    help="OpsAI Terminal Assistant - 终端智能运维助手",
    add_completion=False,
)
config_app = typer.Typer(help="配置管理命令")
template_app = typer.Typer(help="任务模板管理命令")
app.add_typer(config_app, name="config")
app.add_typer(template_app, name="template")

console = Console()


def version_callback(value: bool) -> None:
    """版本回调"""
    if value:
        console.print(f"OpsAI version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="显示版本号",
    ),
) -> None:
    """OpsAI Terminal Assistant - 终端智能运维助手"""
    pass


@app.command()
def query(
    request: str = typer.Argument(..., help="自然语言请求"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="模拟执行，不实际执行操作"),
) -> None:
    """执行自然语言查询（仅支持安全操作）

    示例:
        opsai query "检查磁盘使用情况"
        opsai query "查找大于100MB的文件"
        opsai query "删除临时文件" --dry-run
    """
    console.print(Panel("[bold blue]OpsAI[/bold blue] - Analyzing your request..."))

    config_manager = ConfigManager()
    config = config_manager.load()

    engine = OrchestratorEngine(config, dry_run=dry_run)

    try:
        result = asyncio.run(engine.react_loop(request))
        console.print(Panel(result, title="Result", border_style="green"))
    except Exception as e:
        console.print(Panel(f"Error: {e!s}", title="Error", border_style="red"))
        raise typer.Exit(1)


@config_app.command("show")
def config_show() -> None:
    """显示当前配置"""
    config_manager = ConfigManager()
    config = config_manager.load()

    console.print(Panel(
        config.model_dump_json(indent=2),
        title="Current Configuration",
        border_style="blue",
    ))


@config_app.command("set-llm")
def config_set_llm(
    model: str = typer.Option(..., "--model", "-m", help="模型名称"),
    base_url: Optional[str] = typer.Option(None, "--base-url", "-u", help="API 端点"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API 密钥"),
) -> None:
    """设置 LLM 配置

    示例:
        opsai config set-llm --model gpt-4o --api-key sk-xxx
        opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1
    """
    config_manager = ConfigManager()
    config = config_manager.load()

    config.llm.model = model
    if base_url:
        config.llm.base_url = base_url
    if api_key:
        config.llm.api_key = api_key

    config_manager.save(config)
    console.print("[green]✓[/green] Configuration saved")


@template_app.command("list")
def template_list() -> None:
    """列出所有可用的任务模板"""
    template_manager = TemplateManager()
    templates = template_manager.list_templates()

    if not templates:
        console.print("[yellow]No templates found[/yellow]")
        return

    from rich.table import Table

    table = Table(title="Available Templates")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Description", style="green")
    table.add_column("Steps", style="yellow")

    for template in templates:
        table.add_row(
            template.name,
            template.category,
            template.description,
            str(len(template.steps)),
        )

    console.print(table)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="模板名称"),
) -> None:
    """显示模板详情"""
    template_manager = TemplateManager()
    template = template_manager.load_template(name)

    if template is None:
        console.print(f"[red]Template not found: {name}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        template.model_dump_json(indent=2),
        title=f"Template: {name}",
        border_style="blue",
    ))


@template_app.command("run")
def template_run(
    name: str = typer.Argument(..., help="模板名称"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="模拟执行"),
    context: Optional[str] = typer.Option(None, "--context", "-c", help="上下文变量（JSON格式）"),
) -> None:
    """运行任务模板

    示例:
        opsai template run disk_cleanup
        opsai template run disk_cleanup --dry-run
        opsai template run service_restart --context '{"container_id": "my-app"}'
    """
    import json

    template_manager = TemplateManager()
    template = template_manager.load_template(name)

    if template is None:
        console.print(f"[red]Template not found: {name}[/red]")
        raise typer.Exit(1)

    # 解析上下文
    context_dict = {}
    if context:
        try:
            context_dict = json.loads(context)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON context: {e!s}[/red]")
            raise typer.Exit(1)

    # 生成指令
    instructions = template_manager.generate_instructions(template, context_dict)

    console.print(Panel(
        f"[bold blue]Running template: {name}[/bold blue]\n"
        f"Steps: {len(instructions)}\n"
        f"Dry-run: {dry_run}",
        border_style="blue",
    ))

    # 执行指令
    config_manager = ConfigManager()
    config = config_manager.load()
    engine = OrchestratorEngine(config, dry_run=dry_run)

    try:
        for idx, instruction in enumerate(instructions, 1):
            console.print(f"\n[bold]Step {idx}/{len(instructions)}:[/bold] {instruction.action}")
            result = asyncio.run(engine.execute_instruction(instruction))
            
            status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
            simulated = " [yellow](simulated)[/yellow]" if result.simulated else ""
            console.print(f"{status} {result.message}{simulated}")

            if not result.success:
                console.print(f"[red]Template execution failed at step {idx}[/red]")
                raise typer.Exit(1)

        console.print("\n[green]✓ Template execution completed successfully[/green]")
    except Exception as e:
        console.print(Panel(f"Error: {e!s}", title="Error", border_style="red"))
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
