"""系统操作 Worker"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Union, cast

from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker


class SystemWorker(BaseWorker):
    """系统文件操作 Worker

    支持的操作:
    - find_large_files: 查找大文件
    - check_disk_usage: 检查磁盘使用情况
    - delete_files: 删除文件
    """

    @property
    def name(self) -> str:
        return "system"

    def get_capabilities(self) -> list[str]:
        return ["find_large_files", "check_disk_usage", "delete_files"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行系统操作"""
        handlers: dict[
            str,
            Callable[[dict[str, ArgValue]], Awaitable[WorkerResult]],
        ] = {
            "find_large_files": self._find_large_files,
            "check_disk_usage": self._check_disk_usage,
            "delete_files": self._delete_files,
        }

        handler = handlers.get(action)
        if handler is None:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        try:
            return await handler(args)
        except Exception as e:
            return WorkerResult(
                success=False,
                message=f"Error executing {action}: {e!s}",
            )

    async def _find_large_files(
        self,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """查找大文件

        Args:
            args: 包含 path 和 min_size_mb
        """
        path_str = args.get("path", ".")
        if not isinstance(path_str, str):
            return WorkerResult(success=False, message="path must be a string")

        min_size_mb = args.get("min_size_mb", 100)
        if not isinstance(min_size_mb, int):
            return WorkerResult(success=False, message="min_size_mb must be an integer")

        path = Path(path_str)
        if not path.exists():
            return WorkerResult(success=False, message=f"Path does not exist: {path}")

        min_size_bytes = min_size_mb * 1024 * 1024
        large_files: list[dict[str, str | int]] = []

        for file_path in path.rglob("*"):
            if file_path.is_file():
                try:
                    size = file_path.stat().st_size
                    if size >= min_size_bytes:
                        large_files.append({
                            "path": str(file_path),
                            "size_mb": size // (1024 * 1024),
                        })
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
    ) -> WorkerResult:
        """检查磁盘使用情况"""
        path_str = args.get("path", "/")
        if not isinstance(path_str, str):
            return WorkerResult(success=False, message="path must be a string")

        try:
            usage = shutil.disk_usage(path_str)
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
    ) -> WorkerResult:
        """删除文件

        Args:
            args: 包含 files 列表
        """
        files = args.get("files", [])
        if not isinstance(files, list):
            return WorkerResult(success=False, message="files must be a list")
        
        if len(files) == 0:
            return WorkerResult(success=False, message="files list cannot be empty")

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
