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
from src.orchestrator.safety import check_safety
from src.templates import TemplateManager
from src.types import RiskLevel, WorkerResult

app = typer.Typer(
    name="opsai",
    help="OpsAI Terminal Assistant - 终端智能运维助手",
    add_completion=False,
)
config_app = typer.Typer(help="配置管理命令")
template_app = typer.Typer(help="任务模板管理命令")
cache_app = typer.Typer(help="缓存管理命令")
app.add_typer(config_app, name="config")
app.add_typer(template_app, name="template")
app.add_typer(cache_app, name="cache")

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


@app.command()
def deploy(
    repo_url: str = typer.Argument(..., help="GitHub 仓库 URL"),
    target_dir: str = typer.Option("~/projects", "--target-dir", "-t", help="部署目标目录"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="模拟执行，不实际部署"),
) -> None:
    """一键部署 GitHub 项目

    自动完成：分析项目类型 → 克隆仓库 → 配置环境 → 启动服务

    示例:
        opsai deploy https://github.com/user/my-app
        opsai deploy https://github.com/user/my-app --target-dir ~/myprojects
        opsai deploy https://github.com/user/my-app --dry-run
    """
    with console.status("[bold green]正在部署项目..."):
        result = asyncio.run(_deploy_project(repo_url, target_dir, dry_run))

    if result.success:
        console.print(Panel(result.message, title="✅ 部署成功", border_style="green"))
    else:
        console.print(Panel(result.message, title="❌ 部署失败", border_style="red"))
        raise typer.Exit(code=1)


async def _deploy_project(repo_url: str, target_dir: str, dry_run: bool) -> WorkerResult:
    """执行部署"""
    from src.llm.client import LLMClient
    from src.workers.deploy import DeployWorker
    from src.workers.http import HttpWorker
    from src.workers.shell import ShellWorker

    config_manager = ConfigManager()
    config = config_manager.load()

    http_worker = HttpWorker(config.http)
    shell_worker = ShellWorker()
    llm_client = LLMClient(config.llm)
    deploy_worker = DeployWorker(http_worker, shell_worker, llm_client)

    return await deploy_worker.execute(
        "deploy",
        {
            "repo_url": repo_url,
            "target_dir": target_dir,
            "dry_run": dry_run,
        },
    )


@config_app.command("show")
def config_show() -> None:
    """显示当前配置"""
    config_manager = ConfigManager()
    config = config_manager.load()

    console.print(
        Panel(
            config.model_dump_json(indent=2),
            title="Current Configuration",
            border_style="blue",
        )
    )


@config_app.command("set-llm")
def config_set_llm(
    model: str = typer.Option(..., "--model", "-m", help="模型名称"),
    base_url: Optional[str] = typer.Option(None, "--base-url", "-u", help="API 端点"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API 密钥"),
    temperature: Optional[float] = typer.Option(
        None, "--temperature", help="采样温度（建议 0-0.3）"
    ),
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
    if temperature is not None:
        config.llm.temperature = temperature

    config_manager.save(config)
    console.print("[green]✓[/green] Configuration saved")


@config_app.command("set-http")
def config_set_http(
    github_token: Optional[str] = typer.Option(None, "--github-token", "-t", help="GitHub Token"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="请求超时时间(秒)"),
) -> None:
    """设置 HTTP 配置

    示例:
        opsai config set-http --github-token ghp_xxxx
        opsai config set-http --timeout 60
    """
    config_manager = ConfigManager()
    config = config_manager.load()

    if github_token is not None:
        config.http.github_token = github_token
    if timeout is not None:
        config.http.timeout = timeout

    config_manager.save(config)
    console.print("[green]✓[/green] HTTP configuration saved")


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

    console.print(
        Panel(
            template.model_dump_json(indent=2),
            title=f"Template: {name}",
            border_style="blue",
        )
    )


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

    console.print(
        Panel(
            f"[bold blue]Running template: {name}[/bold blue]\n"
            f"Steps: {len(instructions)}\n"
            f"Dry-run: {dry_run}",
            border_style="blue",
        )
    )

    # 执行指令
    config_manager = ConfigManager()
    config = config_manager.load()
    engine = OrchestratorEngine(config, dry_run=dry_run)

    try:
        risk_order: dict[RiskLevel, int] = {
            "safe": 0,
            "medium": 1,
            "high": 2,
        }

        for idx, instruction in enumerate(instructions, 1):
            risk = check_safety(instruction)

            if not dry_run:
                if risk_order[risk] > risk_order[config.safety.cli_max_risk]:
                    console.print(
                        f"[red]Step {idx} blocked: risk={risk} exceeds CLI limit "
                        f"{config.safety.cli_max_risk}[/red]"
                    )
                    raise typer.Exit(1)

                if (
                    risk == "high"
                    and config.safety.require_dry_run_for_high_risk
                ):
                    console.print(
                        f"[red]Step {idx} blocked: high-risk action requires --dry-run first[/red]"
                    )
                    raise typer.Exit(1)

            console.print(f"\n[bold]Step {idx}/{len(instructions)}:[/bold] {instruction.action}")
            console.print(f"[dim]Risk: {risk}[/dim]")
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


@cache_app.command("list")
def cache_list() -> None:
    """列出所有缓存的分析模板"""
    from rich.table import Table

    from src.workers.analyze import AnalyzeTemplateCache

    cache = AnalyzeTemplateCache()
    templates = cache.list_all()

    if not templates:
        console.print("[dim]No cached templates[/dim]")
        return

    table = Table(title="Cached Analyze Templates")
    table.add_column("Type", style="cyan")
    table.add_column("Hit Count", style="magenta", justify="right")
    table.add_column("Created At", style="green")
    table.add_column("Commands", style="yellow")

    for name, template in templates.items():
        # 格式化命令列表（截断过长的命令）
        commands_str = ", ".join(
            cmd[:30] + "..." if len(cmd) > 30 else cmd for cmd in template.commands[:3]
        )
        if len(template.commands) > 3:
            commands_str += f" (+{len(template.commands) - 3} more)"

        table.add_row(
            name,
            str(template.hit_count),
            template.created_at[:19],  # 截取日期部分
            commands_str,
        )

    console.print(table)


@cache_app.command("show")
def cache_show(
    target_type: str = typer.Argument(..., help="对象类型（如 docker, process, port）"),
) -> None:
    """显示指定类型的缓存模板详情"""
    from src.workers.analyze import AnalyzeTemplateCache

    cache = AnalyzeTemplateCache()
    templates = cache.list_all()

    if target_type not in templates:
        console.print(f"[red]Cache not found for type: {target_type}[/red]")
        raise typer.Exit(1)

    template = templates[target_type]

    console.print(
        Panel(
            f"[bold]Type:[/bold] {target_type}\n"
            f"[bold]Hit Count:[/bold] {template.hit_count}\n"
            f"[bold]Created At:[/bold] {template.created_at}\n\n"
            f"[bold]Commands:[/bold]\n" + "\n".join(f"  - {cmd}" for cmd in template.commands),
            title=f"Cache: {target_type}",
            border_style="blue",
        )
    )


@cache_app.command("clear")
def cache_clear(
    target_type: Optional[str] = typer.Argument(
        None,
        help="要清除的对象类型，不指定则清除全部",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="不询问确认直接清除",
    ),
) -> None:
    """清除缓存的分析模板

    示例:
        opsai cache clear           # 清除所有缓存
        opsai cache clear docker    # 只清除 docker 类型的缓存
        opsai cache clear -f        # 强制清除，不询问
    """
    from src.workers.analyze import AnalyzeTemplateCache

    cache = AnalyzeTemplateCache()

    # 确认清除
    if not force:
        if target_type:
            if not cache.exists(target_type):
                console.print(f"[yellow]No cache found for type: {target_type}[/yellow]")
                return
            confirm_msg = f"Clear cache for type '{target_type}'?"
        else:
            templates = cache.list_all()
            if not templates:
                console.print("[dim]No cached templates to clear[/dim]")
                return
            confirm_msg = f"Clear ALL cached templates ({len(templates)} items)?"

        confirmed = typer.confirm(confirm_msg)
        if not confirmed:
            console.print("[yellow]Cancelled[/yellow]")
            return

    # 执行清除
    count = cache.clear(target_type)

    if target_type:
        console.print(f"[green]✓[/green] Cleared cache for: {target_type}")
    else:
        console.print(f"[green]✓[/green] Cleared all cache ({count} items)")


if __name__ == "__main__":
    app()
