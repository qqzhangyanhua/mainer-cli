"""文件写操作 - 从 SystemWorker 提取的文件写入功能"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union, cast

from src.types import ArgValue, WorkerResult


async def write_file(
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    """创建或覆写文件"""
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(
            success=False,
            message="path parameter is required and must be a string",
        )

    content = args.get("content")
    if not isinstance(content, str):
        return WorkerResult(
            success=False,
            message="content parameter is required and must be a string",
        )

    path = Path(path_str)

    if path.is_dir():
        return WorkerResult(success=False, message=f"Path is a directory: {path}")

    if not path.parent.exists():
        return WorkerResult(
            success=False,
            message=f"Parent directory does not exist: {path.parent}",
        )

    if dry_run:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return WorkerResult(
            success=True,
            message=(
                f"[DRY-RUN] Would write {len(content)} chars to {path}\nContent preview:\n{preview}"
            ),
            simulated=True,
        )

    try:
        path.write_text(content, encoding="utf-8")
        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {"path": str(path), "size": len(content)},
            ),
            message=f"Successfully wrote {len(content)} chars to {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error writing file: {e!s}")


async def append_to_file(
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    """追加内容到文件"""
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(
            success=False,
            message="path parameter is required and must be a string",
        )

    content = args.get("content")
    if not isinstance(content, str):
        return WorkerResult(
            success=False,
            message="content parameter is required and must be a string",
        )

    path = Path(path_str)

    if not path.exists():
        return WorkerResult(success=False, message=f"File not found: {path}")

    if not path.is_file():
        return WorkerResult(success=False, message=f"Path is not a file: {path}")

    if dry_run:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return WorkerResult(
            success=True,
            message=(
                f"[DRY-RUN] Would append {len(content)} chars to {path}\n"
                f"Content to append:\n{preview}"
            ),
            simulated=True,
        )

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {"path": str(path), "appended_size": len(content)},
            ),
            message=f"Successfully appended {len(content)} chars to {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error appending to file: {e!s}")


async def replace_in_file(
    args: dict[str, ArgValue],
    dry_run: bool = False,
) -> WorkerResult:
    """查找替换文件内容"""
    path_str = args.get("path")
    if not isinstance(path_str, str):
        return WorkerResult(
            success=False,
            message="path parameter is required and must be a string",
        )

    old = args.get("old")
    if not isinstance(old, str):
        return WorkerResult(
            success=False,
            message="old parameter is required and must be a string",
        )

    new = args.get("new")
    if not isinstance(new, str):
        return WorkerResult(
            success=False,
            message="new parameter is required and must be a string",
        )

    use_regex = args.get("regex", False)
    if isinstance(use_regex, str):
        use_regex = use_regex.lower() == "true"

    max_count = args.get("count")
    if max_count is not None and not isinstance(max_count, int):
        return WorkerResult(success=False, message="count must be an integer")

    path = Path(path_str)

    if not path.exists():
        return WorkerResult(success=False, message=f"File not found: {path}")

    if not path.is_file():
        return WorkerResult(success=False, message=f"Path is not a file: {path}")

    try:
        file_content = path.read_text(encoding="utf-8")
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error reading file: {e!s}")

    if use_regex:
        try:
            pattern = re.compile(old)
        except re.error as e:
            return WorkerResult(success=False, message=f"Invalid regex pattern: {e!s}")
        match_count = len(pattern.findall(file_content))
    else:
        match_count = file_content.count(old)

    if match_count == 0:
        return WorkerResult(
            success=True,
            message=f"No matches found for '{old}'",
            task_completed=True,
        )

    effective_count = min(match_count, max_count) if max_count else match_count

    if dry_run:
        return WorkerResult(
            success=True,
            message=(
                f"[DRY-RUN] Would replace in {path}\n"
                f'  "{old}" -> "{new}"\n'
                f"  Matches found: {match_count}, would replace: {effective_count}"
            ),
            simulated=True,
        )

    if use_regex:
        count_arg = max_count if max_count else 0
        new_content, actual_count = re.subn(old, new, file_content, count=count_arg)
    else:
        if max_count:
            new_content = file_content.replace(old, new, max_count)
            actual_count = min(match_count, max_count)
        else:
            new_content = file_content.replace(old, new)
            actual_count = match_count

    try:
        path.write_text(new_content, encoding="utf-8")
        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {"path": str(path), "replacements": actual_count},
            ),
            message=f"Replaced {actual_count} occurrence(s) in {path}",
            task_completed=True,
        )
    except PermissionError:
        return WorkerResult(success=False, message=f"Permission denied: {path}")
    except OSError as e:
        return WorkerResult(success=False, message=f"Error writing file: {e!s}")
