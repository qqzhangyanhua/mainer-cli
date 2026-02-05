"""部署工作流状态定义"""

from __future__ import annotations

from typing import Literal

from typing_extensions import TypedDict


class DeployState(TypedDict, total=False):
    """部署工作流状态

    使用 total=False 允许部分字段为可选
    """

    # 输入参数
    repo_url: str
    target_dir: str
    dry_run: bool

    # 分析结果
    owner: str
    repo: str
    project_type: str  # docker, python, nodejs, go, rust, unknown
    key_files: list[str]
    readme_summary: str

    # 执行状态
    clone_path: str
    current_step: Literal["analyze", "clone", "setup", "start", "done", "error"]
    error_message: str

    # 输出
    steps_completed: list[str]
    final_message: str


# 状态步骤常量
STEP_ANALYZE = "analyze"
STEP_CLONE = "clone"
STEP_SETUP = "setup"
STEP_START = "start"
STEP_DONE = "done"
STEP_ERROR = "error"
