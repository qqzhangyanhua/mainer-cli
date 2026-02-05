"""检查点存储管理"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from langgraph.checkpoint.memory import MemorySaver

# SqliteSaver 可能在独立包中，尝试导入
try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    SQLITE_AVAILABLE = True
except ImportError:
    # 如果 SqliteSaver 不可用，定义占位符类型
    SqliteSaver = None  # type: ignore[assignment,misc]
    SQLITE_AVAILABLE = False


def get_checkpoint_saver(
    use_sqlite: bool = False,
    db_path: Union[str, Path, None] = None,
) -> MemorySaver:
    """获取检查点存储器

    Args:
        use_sqlite: 是否使用 SQLite 持久化（默认使用内存存储）
        db_path: SQLite 数据库路径（仅当 use_sqlite=True 时有效）

    Returns:
        检查点存储器实例

    Note:
        如果 SqliteSaver 不可用，即使 use_sqlite=True 也会回退到 MemorySaver
    """
    if not use_sqlite or not SQLITE_AVAILABLE:
        if use_sqlite and not SQLITE_AVAILABLE:
            import warnings

            warnings.warn(
                "SqliteSaver not available. Falling back to MemorySaver. "
                "Install langgraph-checkpoint-sqlite for persistent storage.",
                RuntimeWarning,
                stacklevel=2,
            )
        return MemorySaver()

    # 使用 SQLite 持久化
    if db_path is None:
        # 默认路径：~/.opsai/checkpoints.db
        home_dir = Path.home()
        opsai_dir = home_dir / ".opsai"
        opsai_dir.mkdir(exist_ok=True)
        db_path = opsai_dir / "checkpoints.db"
    else:
        db_path = Path(db_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # 创建 SQLite 连接字符串
    conn_string = f"sqlite:///{db_path}"

    assert SqliteSaver is not None, "SqliteSaver should be available"
    return SqliteSaver.from_conn_string(conn_string)  # type: ignore[return-value]


def get_default_checkpoint_path() -> Path:
    """获取默认检查点数据库路径

    Returns:
        默认数据库路径
    """
    home_dir = Path.home()
    return home_dir / ".opsai" / "checkpoints.db"


def clear_checkpoints(db_path: Union[str, Path, None] = None) -> bool:
    """清空检查点数据库

    Args:
        db_path: 数据库路径（None 则使用默认路径）

    Returns:
        是否成功清空
    """
    if db_path is None:
        db_path = get_default_checkpoint_path()
    else:
        db_path = Path(db_path).expanduser()

    if not db_path.exists():
        return True

    try:
        os.remove(db_path)
        return True
    except Exception:
        return False
