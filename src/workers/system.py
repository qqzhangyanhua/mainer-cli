"""系统操作 Worker"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Union, cast  # noqa: F401 – used by read-only methods

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.file_ops import append_to_file, replace_in_file, write_file
from src.workers.path_utils import normalize_path


class SystemWorker(BaseWorker):
    """系统文件操作 Worker

    支持的操作:
    - list_files: 列出目录下的文件
    - find_large_files: 查找大文件
    - check_disk_usage: 检查磁盘使用情况
    - delete_files: 删除文件
    - write_file: 创建或覆写文件
    - append_to_file: 追加内容到文件
    - replace_in_file: 查找替换文件内容
    """

    @property
    def name(self) -> str:
        return "system"

    def get_capabilities(self) -> list[str]:
        return [
            "list_files",
            "find_large_files",
            "check_disk_usage",
            "delete_files",
            "write_file",
            "append_to_file",
            "replace_in_file",
        ]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行系统操作"""
        # 检查 dry_run 模式
        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        handlers: dict[
            str,
            Callable[[dict[str, ArgValue], bool], Awaitable[WorkerResult]],
        ] = {
            "list_files": self._list_files,
            "find_large_files": self._find_large_files,
            "check_disk_usage": self._check_disk_usage,
            "delete_files": self._delete_files,
            "write_file": self._write_file,
            "append_to_file": self._append_to_file,
            "replace_in_file": self._replace_in_file,
        }

        handler = handlers.get(action)
        if handler is None:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        try:
            return await handler(args, dry_run=dry_run)
        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Error executing {action}: {e!s}",
            )

    async def _list_files(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """列出目录下的文件

        Args:
            args: 包含 path（可选，默认当前目录）
            dry_run: 是否为模拟执行
        """
        path_str = args.get("path", ".")
        if not isinstance(path_str, str):
            return WorkerResult(success=False, message="path must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would list files in {path_str}",
                simulated=True,
            )

        normalized = normalize_path(path_str)
        path = Path(normalized)
        if not path.exists():
            return WorkerResult(success=False, message=f"Path does not exist: {path}")

        if not path.is_dir():
            return WorkerResult(success=False, message=f"Path is not a directory: {path}")

        try:
            files: list[dict[str, str]] = []
            for item in sorted(path.iterdir()):
                files.append(
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                    }
                )

            return WorkerResult(
                success=True,
                data=cast(list[dict[str, Union[str, int]]], files),
                message=f"Found {len(files)} items in {path}",
                task_completed=True,
            )
        except (PermissionError, OSError) as e:
            return WorkerResult(success=False, message=f"Cannot list directory: {e!s}")

    async def _find_large_files(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """查找大文件

        Args:
            args: 包含 path 和 min_size_mb
            dry_run: 是否为模拟执行
        """
        path_str = args.get("path", ".")
        if not isinstance(path_str, str):
            return WorkerResult(success=False, message="path must be a string")

        min_size_mb = args.get("min_size_mb", 100)
        if not isinstance(min_size_mb, int):
            return WorkerResult(success=False, message="min_size_mb must be an integer")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would search for files larger than {min_size_mb}MB in {path_str}",
                simulated=True,
            )

        normalized = normalize_path(path_str)
        path = Path(normalized)
        if not path.exists():
            return WorkerResult(success=False, message=f"Path does not exist: {path}")

        min_size_bytes = min_size_mb * 1024 * 1024
        large_files: list[dict[str, str | int]] = []

        for file_path in path.rglob("*"):
            if file_path.is_file():
                try:
                    size = file_path.stat().st_size
                    if size >= min_size_bytes:
                        large_files.append(
                            {
                                "path": str(file_path),
                                "size_mb": size // (1024 * 1024),
                            }
                        )
                except (PermissionError, OSError):
                    continue

        # 按大小降序排序
        large_files.sort(key=lambda x: x["size_mb"], reverse=True)

        return WorkerResult(
            success=True,
            data=large_files,
            message=f"Found {len(large_files)} files larger than {min_size_mb}MB",
        )

    async def _check_disk_usage(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """检查磁盘使用情况"""
        path_str = args.get("path", "/")
        if not isinstance(path_str, str):
            return WorkerResult(success=False, message="path must be a string")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would check disk usage for {path_str}",
                simulated=True,
            )

        try:
            normalized = normalize_path(path_str, default="/")
            usage = shutil.disk_usage(normalized)
            data: dict[str, int] = {
                "total": usage.total // (1024 * 1024 * 1024),  # GB
                "used": usage.used // (1024 * 1024 * 1024),
                "free": usage.free // (1024 * 1024 * 1024),
                "percent_used": int(usage.used / usage.total * 100),
            }
            return WorkerResult(
                success=True,
                data=cast(dict[str, Union[str, int]], data),
                message=f"Disk usage: {data['percent_used']}% used",
            )
        except OSError as e:
            return WorkerResult(success=False, message=f"Cannot check disk usage: {e!s}")

    async def _delete_files(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """删除文件

        Args:
            args: 包含 files 列表
            dry_run: 是否为模拟执行
        """
        files = args.get("files", [])
        if not isinstance(files, list):
            # 兼容单个字符串参数
            if isinstance(files, str):
                files = [files]
            else:
                return WorkerResult(success=False, message="files must be a list")

        # 兼容：LLM 可能传了 "path" 而非 "files"
        if len(files) == 0:
            path_arg = args.get("path")
            if isinstance(path_arg, str) and path_arg:
                files = [path_arg]

        if len(files) == 0:
            return WorkerResult(success=False, message="files list cannot be empty")

        if dry_run:
            return WorkerResult(
                success=True,
                message=f"[DRY-RUN] Would delete {len(files)} files: {', '.join(str(f) for f in files[:3])}{'...' if len(files) > 3 else ''}",
                simulated=True,
            )

        deleted: list[str] = []
        errors: list[str] = []

        for file_path in files:
            if not isinstance(file_path, str):
                errors.append(f"Invalid path type: {file_path}")
                continue

            path = Path(file_path)
            try:
                if path.is_file():
                    path.unlink()
                    deleted.append(str(path))
                elif path.is_dir():
                    errors.append(f"Cannot delete directory: {path}")
                else:
                    errors.append(f"File not found: {path}")
            except (PermissionError, OSError) as e:
                errors.append(f"Cannot delete {path}: {e!s}")

        success = len(errors) == 0
        message_parts = []
        if deleted:
            message_parts.append(f"Deleted {len(deleted)} files")
        if errors:
            message_parts.append(f"{len(errors)} errors")

        # 构建符合类型要求的数据结构
        result_data: list[dict[str, str]] = []
        for deleted_path in deleted:
            result_data.append({"type": "deleted", "path": deleted_path})
        for error_msg in errors:
            result_data.append({"type": "error", "message": error_msg})

        return WorkerResult(
            success=success,
            data=cast(list[dict[str, Union[str, int]]], result_data),
            message=", ".join(message_parts) if message_parts else "No files to delete",
            task_completed=success,
        )

    async def _write_file(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """创建或覆写文件（委托到 file_ops）"""
        return await write_file(args, dry_run)

    async def _append_to_file(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """追加内容到文件（委托到 file_ops）"""
        return await append_to_file(args, dry_run)

    async def _replace_in_file(
        self,
        args: dict[str, ArgValue],
        dry_run: bool = False,
    ) -> WorkerResult:
        """查找替换文件内容（委托到 file_ops）"""
        return await replace_in_file(args, dry_run)
