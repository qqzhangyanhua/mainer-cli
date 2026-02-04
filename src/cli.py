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


app = typer.Typer(
    name="opsai",
    help="OpsAI Terminal Assistant - 终端智能运维助手",
    add_completion=False,
)
config_app = typer.Typer(help="配置管理命令")
app.add_typer(config_app, name="config")

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
) -> None:
    """执行自然语言查询（仅支持安全操作）

    示例:
        opsai query "检查磁盘使用情况"
        opsai query "查找大于100MB的文件"
    """
    console.print(Panel("[bold blue]OpsAI[/bold blue] - Analyzing your request..."))

    config_manager = ConfigManager()
    config = config_manager.load()

    engine = OrchestratorEngine(config)

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


if __name__ == "__main__":
    app()
