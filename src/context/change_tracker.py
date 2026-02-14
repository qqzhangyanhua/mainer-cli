"""变更管理 — 操作快照与回滚"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


ChangeType = Literal["file_write", "file_delete", "file_modify", "command"]


class ChangeRecord(BaseModel):
    """单条变更记录"""

    change_id: str = Field(..., description="变更 ID")
    change_type: ChangeType = Field(..., description="变更类型")
    timestamp: float = Field(default_factory=time.time, description="时间戳")
    description: str = Field(default="", description="变更描述")

    # 文件变更
    file_path: Optional[str] = Field(default=None, description="受影响的文件路径")
    backup_path: Optional[str] = Field(default=None, description="备份文件路径")
    new_content: Optional[str] = Field(default=None, description="新内容（用于 write）")

    # 命令变更
    command: Optional[str] = Field(default=None, description="执行的命令")

    rollback_available: bool = Field(default=False, description="是否可回滚")
    rolled_back: bool = Field(default=False, description="是否已回滚")


class ChangeTracker:
    """变更追踪器

    在执行破坏性操作前自动备份，支持回滚到操作前状态。
    存储路径: ~/.opsai/changes/
    """

    MAX_RECORDS = 100

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or Path.home() / ".opsai" / "changes"
        self._backup_dir = self._base_dir / "backups"
        self._index_path = self._base_dir / "index.json"
        self._records: list[ChangeRecord] = []
        self._counter = 0
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._load_index()

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            with open(self._index_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._records = [ChangeRecord.model_validate(r) for r in data]
                self._counter = len(self._records)
        except (json.JSONDecodeError, ValueError):
            pass

    def _save_index(self) -> None:
        data = [r.model_dump() for r in self._records]
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _next_id(self) -> str:
        self._counter += 1
        return f"chg-{self._counter:04d}"

    def snapshot_file(self, file_path: str, description: str = "") -> str:
        """在修改文件前创建快照

        Args:
            file_path: 文件路径
            description: 变更描述

        Returns:
            change_id
        """
        path = Path(file_path)
        change_id = self._next_id()
        backup_path: Optional[str] = None
        rollback_available = False

        if path.exists():
            # 备份现有文件
            backup_name = f"{change_id}_{path.name}"
            backup_dest = self._backup_dir / backup_name
            shutil.copy2(str(path), str(backup_dest))
            backup_path = str(backup_dest)
            rollback_available = True

        record = ChangeRecord(
            change_id=change_id,
            change_type="file_modify" if path.exists() else "file_write",
            description=description or f"修改文件: {file_path}",
            file_path=file_path,
            backup_path=backup_path,
            rollback_available=rollback_available,
        )
        self._records.append(record)
        self._enforce_limit()
        self._save_index()
        return change_id

    def record_delete(self, file_path: str, description: str = "") -> str:
        """记录文件删除（先备份）

        Args:
            file_path: 被删除文件的路径
            description: 变更描述

        Returns:
            change_id
        """
        path = Path(file_path)
        change_id = self._next_id()
        backup_path: Optional[str] = None
        rollback_available = False

        if path.exists():
            backup_name = f"{change_id}_{path.name}"
            backup_dest = self._backup_dir / backup_name
            shutil.copy2(str(path), str(backup_dest))
            backup_path = str(backup_dest)
            rollback_available = True

        record = ChangeRecord(
            change_id=change_id,
            change_type="file_delete",
            description=description or f"删除文件: {file_path}",
            file_path=file_path,
            backup_path=backup_path,
            rollback_available=rollback_available,
        )
        self._records.append(record)
        self._enforce_limit()
        self._save_index()
        return change_id

    def record_command(self, command: str, description: str = "") -> str:
        """记录命令执行

        Args:
            command: 执行的命令
            description: 变更描述

        Returns:
            change_id
        """
        change_id = self._next_id()
        record = ChangeRecord(
            change_id=change_id,
            change_type="command",
            description=description or f"执行命令: {command}",
            command=command,
            rollback_available=False,
        )
        self._records.append(record)
        self._enforce_limit()
        self._save_index()
        return change_id

    def rollback(self, change_id: str) -> tuple[bool, str]:
        """回滚指定变更

        Args:
            change_id: 变更 ID

        Returns:
            (成功, 消息)
        """
        record = self._find_record(change_id)
        if record is None:
            return False, f"变更记录不存在: {change_id}"

        if record.rolled_back:
            return False, f"该变更已回滚: {change_id}"

        if not record.rollback_available:
            return False, f"该变更不支持回滚: {change_id} ({record.change_type})"

        if record.file_path is None or record.backup_path is None:
            return False, "缺少文件路径信息"

        backup = Path(record.backup_path)
        if not backup.exists():
            return False, f"备份文件不存在: {record.backup_path}"

        target = Path(record.file_path)
        try:
            if record.change_type == "file_delete":
                # 恢复被删除的文件
                shutil.copy2(str(backup), str(target))
            elif record.change_type in ("file_modify", "file_write"):
                if record.change_type == "file_write" and target.exists():
                    # 新建的文件，回滚 = 删除
                    target.unlink()
                else:
                    # 修改的文件，回滚 = 恢复备份
                    shutil.copy2(str(backup), str(target))

            record.rolled_back = True
            self._save_index()
            return True, f"已回滚: {record.description}"

        except OSError as e:
            return False, f"回滚失败: {e}"

    def list_changes(self, limit: int = 20) -> list[ChangeRecord]:
        """列出最近的变更记录

        Args:
            limit: 返回条数

        Returns:
            变更记录列表（最新在前）
        """
        return list(reversed(self._records[-limit:]))

    def get_change(self, change_id: str) -> Optional[ChangeRecord]:
        """获取单条变更记录"""
        return self._find_record(change_id)

    def _find_record(self, change_id: str) -> Optional[ChangeRecord]:
        for record in self._records:
            if record.change_id == change_id:
                return record
        return None

    def _enforce_limit(self) -> None:
        """超出上限时清理最旧记录"""
        while len(self._records) > self.MAX_RECORDS:
            old = self._records.pop(0)
            # 清理备份文件
            if old.backup_path:
                backup = Path(old.backup_path)
                if backup.exists():
                    backup.unlink(missing_ok=True)

    @property
    def size(self) -> int:
        return len(self._records)
