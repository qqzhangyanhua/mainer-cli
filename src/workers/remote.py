"""远程主机 SSH 执行 Worker"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union, cast

from src.config.manager import RemoteConfig
from src.types import ArgValue, HostConfig, WorkerResult
from src.workers.base import BaseWorker

# 输出截断常量（与 ShellWorker 保持一致）
MAX_OUTPUT_LENGTH = 4000
TRUNCATE_HEAD = 2000
TRUNCATE_TAIL = 2000


class RemoteWorker(BaseWorker):
    """远程主机 SSH 执行 Worker

    支持的操作:
    - execute: 在远程主机上执行命令
    - list_hosts: 列出已配置的远程主机
    - test_connection: 测试与远程主机的连接
    """

    def __init__(self, config: RemoteConfig) -> None:
        self._config = config
        self._hosts: dict[str, HostConfig] = {}
        for host in config.hosts:
            # 使用 address 作为 key，确保唯一
            self._hosts[host.address] = host

    @property
    def name(self) -> str:
        return "remote"

    def get_capabilities(self) -> list[str]:
        return ["execute", "list_hosts", "test_connection"]

    def _resolve_host(self, host_id: str) -> Optional[HostConfig]:
        """根据地址或标签解析主机配置"""
        # 精确匹配地址
        if host_id in self._hosts:
            return self._hosts[host_id]

        # 标签匹配（返回第一个匹配的）
        for host in self._hosts.values():
            if host_id in host.labels:
                return host

        return None

    def _resolve_key_path(self, host: HostConfig) -> Optional[str]:
        """解析 SSH 私钥路径，支持 ~ 展开"""
        key_path = host.key_path or self._config.default_key_path
        if key_path:
            return str(Path(key_path).expanduser())
        return None

    def _truncate_output(self, output: str) -> tuple[str, bool]:
        """截断过长输出"""
        if len(output) <= MAX_OUTPUT_LENGTH:
            return output, False

        truncated_chars = len(output) - TRUNCATE_HEAD - TRUNCATE_TAIL
        head = output[:TRUNCATE_HEAD]
        tail = output[-TRUNCATE_TAIL:]
        return (
            f"{head}\n\n... [truncated {truncated_chars} characters] ...\n\n{tail}",
            True,
        )

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        if action == "list_hosts":
            return self._list_hosts()
        if action == "test_connection":
            return await self._test_connection(args)
        if action == "execute":
            return await self._execute_remote(args)
        return WorkerResult(success=False, message=f"Unknown action: {action}")

    def _list_hosts(self) -> WorkerResult:
        """列出所有已配置的远程主机"""
        if not self._hosts:
            return WorkerResult(
                success=True,
                message="未配置任何远程主机。使用 opsai host add 添加主机。",
                task_completed=True,
            )

        hosts_data: list[dict[str, Union[str, int]]] = []
        for addr, host in self._hosts.items():
            hosts_data.append({
                "address": addr,
                "port": host.port,
                "user": host.user,
                "labels": ", ".join(host.labels) if host.labels else "",
            })

        lines = ["已配置的远程主机:"]
        for h in hosts_data:
            labels = f" [{h['labels']}]" if h["labels"] else ""
            lines.append(f"  - {h['user']}@{h['address']}:{h['port']}{labels}")

        return WorkerResult(
            success=True,
            data=hosts_data,
            message="\n".join(lines),
            task_completed=True,
        )

    async def _test_connection(self, args: dict[str, ArgValue]) -> WorkerResult:
        """测试 SSH 连接"""
        try:
            import asyncssh
        except ImportError:
            return WorkerResult(
                success=False,
                message="asyncssh 未安装。运行: uv pip install asyncssh",
            )

        host_id = str(args.get("host", ""))
        if not host_id:
            return WorkerResult(success=False, message="缺少参数: host")

        host = self._resolve_host(host_id)
        if host is None:
            return WorkerResult(
                success=False,
                message=f"未找到主机: {host_id}。使用 opsai host list 查看已配置主机。",
            )

        key_path = self._resolve_key_path(host)

        try:
            conn_kwargs: dict[str, object] = {
                "host": host.address,
                "port": host.port,
                "username": host.user,
                "known_hosts": None,  # 首版简化，跳过 known_hosts 检查
                "connect_timeout": self._config.connect_timeout,
            }
            if key_path:
                conn_kwargs["client_keys"] = [key_path]

            async with asyncssh.connect(**conn_kwargs) as conn:  # type: ignore[arg-type]
                result = await conn.run("echo ok", timeout=5)
                if result.exit_status == 0:
                    return WorkerResult(
                        success=True,
                        message=f"连接成功: {host.user}@{host.address}:{host.port}",
                        task_completed=True,
                    )
                return WorkerResult(
                    success=False,
                    message=f"连接成功但测试命令失败: exit={result.exit_status}",
                )
        except asyncssh.Error as e:
            return WorkerResult(
                success=False,
                message=f"SSH 连接失败: {host.address} - {e}",
            )
        except OSError as e:
            return WorkerResult(
                success=False,
                message=f"网络错误: {host.address} - {e}",
            )

    async def _execute_remote(self, args: dict[str, ArgValue]) -> WorkerResult:
        """在远程主机上执行命令"""
        try:
            import asyncssh
        except ImportError:
            return WorkerResult(
                success=False,
                message="asyncssh 未安装。运行: uv pip install asyncssh",
            )

        host_id = str(args.get("host", ""))
        command = str(args.get("command", ""))
        if not host_id:
            return WorkerResult(success=False, message="缺少参数: host")
        if not command:
            return WorkerResult(success=False, message="缺少参数: command")

        # 检查 dry_run
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        host = self._resolve_host(host_id)
        if host is None:
            return WorkerResult(
                success=False,
                message=f"未找到主机: {host_id}。使用 opsai host list 查看已配置主机。",
            )

        if dry_run:
            return WorkerResult(
                success=True,
                message=(
                    f"[DRY-RUN] Would execute on {host.user}@{host.address}: {command}"
                ),
                simulated=True,
            )

        key_path = self._resolve_key_path(host)

        try:
            conn_kwargs: dict[str, object] = {
                "host": host.address,
                "port": host.port,
                "username": host.user,
                "known_hosts": None,
                "connect_timeout": self._config.connect_timeout,
            }
            if key_path:
                conn_kwargs["client_keys"] = [key_path]

            async with asyncssh.connect(**conn_kwargs) as conn:  # type: ignore[arg-type]
                result = await conn.run(
                    command, timeout=self._config.command_timeout
                )
                stdout = result.stdout or ""
                stderr = result.stderr or ""
                exit_code = result.exit_status or 0

                raw_output, truncated = self._truncate_output(str(stdout))

                message_parts = [
                    f"Remote: {host.user}@{host.address}",
                    f"Command: {command}",
                ]
                if stdout:
                    message_parts.append(f"Output:\n{str(stdout).strip()}")
                if stderr:
                    message_parts.append(f"Stderr:\n{str(stderr).strip()}")
                message_parts.append(f"Exit code: {exit_code}")

                return WorkerResult(
                    success=exit_code == 0,
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {
                            "host": host.address,
                            "command": command,
                            "stdout": str(stdout),
                            "stderr": str(stderr),
                            "exit_code": exit_code,
                            "raw_output": raw_output,
                            "truncated": truncated,
                        },
                    ),
                    message="\n".join(message_parts),
                    task_completed=False,
                )

        except asyncssh.Error as e:
            return WorkerResult(
                success=False,
                message=f"SSH 执行失败: {host.address} - {e}",
            )
        except OSError as e:
            return WorkerResult(
                success=False,
                message=f"网络错误: {host.address} - {e}",
            )
        except TimeoutError:
            return WorkerResult(
                success=False,
                message=(
                    f"命令超时（>{self._config.command_timeout}s）: "
                    f"{host.address} - {command}"
                ),
            )
