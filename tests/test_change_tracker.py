"""ChangeTracker 单元测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.context.change_tracker import ChangeTracker


@pytest.fixture
def tracker(tmp_path: Path) -> ChangeTracker:
    return ChangeTracker(base_dir=tmp_path / "changes")


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.txt"
    f.write_text("original content")
    return f


# ------------------------------------------------------------------
# 快照与回滚
# ------------------------------------------------------------------


def test_snapshot_existing_file(tracker: ChangeTracker, sample_file: Path) -> None:
    change_id = tracker.snapshot_file(str(sample_file), "test snapshot")
    assert change_id.startswith("chg-")

    record = tracker.get_change(change_id)
    assert record is not None
    assert record.rollback_available is True
    assert record.change_type == "file_modify"


def test_snapshot_new_file(tracker: ChangeTracker, tmp_path: Path) -> None:
    new_path = tmp_path / "new.txt"
    change_id = tracker.snapshot_file(str(new_path), "new file")

    record = tracker.get_change(change_id)
    assert record is not None
    assert record.rollback_available is False  # 文件不存在，无需备份
    assert record.change_type == "file_write"


def test_rollback_file_modify(
    tracker: ChangeTracker, sample_file: Path
) -> None:
    change_id = tracker.snapshot_file(str(sample_file))

    # 修改文件
    sample_file.write_text("modified content")
    assert sample_file.read_text() == "modified content"

    # 回滚
    success, msg = tracker.rollback(change_id)
    assert success is True
    assert sample_file.read_text() == "original content"


def test_rollback_file_delete(
    tracker: ChangeTracker, sample_file: Path
) -> None:
    change_id = tracker.record_delete(str(sample_file))

    # 删除文件
    sample_file.unlink()
    assert not sample_file.exists()

    # 回滚（恢复）
    success, msg = tracker.rollback(change_id)
    assert success is True
    assert sample_file.exists()
    assert sample_file.read_text() == "original content"


def test_rollback_nonexistent_id(tracker: ChangeTracker) -> None:
    success, msg = tracker.rollback("chg-9999")
    assert success is False
    assert "不存在" in msg


def test_rollback_already_rolled_back(
    tracker: ChangeTracker, sample_file: Path
) -> None:
    change_id = tracker.snapshot_file(str(sample_file))
    sample_file.write_text("changed")
    tracker.rollback(change_id)

    # 第二次回滚
    success, msg = tracker.rollback(change_id)
    assert success is False
    assert "已回滚" in msg


def test_rollback_command_not_supported(tracker: ChangeTracker) -> None:
    change_id = tracker.record_command("rm -rf /tmp/old")
    success, msg = tracker.rollback(change_id)
    assert success is False
    assert "不支持" in msg


# ------------------------------------------------------------------
# 命令记录
# ------------------------------------------------------------------


def test_record_command(tracker: ChangeTracker) -> None:
    change_id = tracker.record_command("docker restart nginx")
    record = tracker.get_change(change_id)
    assert record is not None
    assert record.command == "docker restart nginx"
    assert record.rollback_available is False


# ------------------------------------------------------------------
# 列表与持久化
# ------------------------------------------------------------------


def test_list_changes(tracker: ChangeTracker, sample_file: Path) -> None:
    tracker.snapshot_file(str(sample_file))
    tracker.record_command("ls")
    tracker.record_command("df -h")

    changes = tracker.list_changes()
    assert len(changes) == 3
    # 最新在前
    assert changes[0].command == "df -h"


def test_list_changes_limit(tracker: ChangeTracker) -> None:
    for i in range(10):
        tracker.record_command(f"cmd{i}")

    changes = tracker.list_changes(limit=3)
    assert len(changes) == 3


def test_persistence(tmp_path: Path) -> None:
    base = tmp_path / "changes"
    t1 = ChangeTracker(base_dir=base)
    t1.record_command("echo hello")
    t1.record_command("echo world")

    # 重新加载
    t2 = ChangeTracker(base_dir=base)
    assert t2.size == 2
    changes = t2.list_changes()
    assert changes[0].command == "echo world"


# ------------------------------------------------------------------
# 容量限制
# ------------------------------------------------------------------


def test_enforce_limit(tmp_path: Path) -> None:
    base = tmp_path / "changes"
    tracker = ChangeTracker(base_dir=base)

    for i in range(ChangeTracker.MAX_RECORDS + 20):
        tracker.record_command(f"cmd{i}")

    assert tracker.size <= ChangeTracker.MAX_RECORDS
