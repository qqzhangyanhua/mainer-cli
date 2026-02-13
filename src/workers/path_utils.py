"""路径规范化工具 - 统一所有 Worker 的路径处理"""

from __future__ import annotations

import os
from typing import Optional


def normalize_path(path: Optional[str], default: str = ".") -> str:
    """统一路径处理：expanduser + abspath

    Args:
        path: 输入路径，None 时使用 default
        default: 默认路径

    Returns:
        规范化后的绝对路径
    """
    if path is None:
        return os.path.abspath(os.path.expanduser(default))
    return os.path.abspath(os.path.expanduser(path))
