"""任务模板管理器"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.types import ArgValue, Instruction


class TemplateStep(BaseModel):
    """模板步骤定义"""

    worker: str = Field(..., description="Worker 名称")
    action: str = Field(..., description="动作名称")
    args: dict[str, ArgValue] = Field(default_factory=dict, description="参数")
    description: str = Field(default="", description="步骤描述")


class TaskTemplate(BaseModel):
    """任务模板"""

    name: str = Field(..., description="模板名称")
    description: str = Field(..., description="模板描述")
    category: str = Field(default="general", description="分类")
    steps: list[TemplateStep] = Field(..., description="步骤列表")


class TemplateManager:
    """模板管理器"""

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        """初始化模板管理器

        Args:
            template_dir: 模板目录，默认为 ~/.opsai/templates
        """
        self._template_dir = template_dir or Path.home() / ".opsai" / "templates"
        self._ensure_templates_exist()

    def _ensure_templates_exist(self) -> None:
        """确保模板目录和默认模板存在"""
        self._template_dir.mkdir(parents=True, exist_ok=True)

        # 如果目录为空，创建默认模板
        if not any(self._template_dir.glob("*.json")):
            self._create_default_templates()

    def _create_default_templates(self) -> None:
        """创建默认模板"""
        default_templates = [
            TaskTemplate(
                name="disk_cleanup",
                description="磁盘空间清理标准流程",
                category="maintenance",
                steps=[
                    TemplateStep(
                        worker="system",
                        action="check_disk_usage",
                        args={"path": "/"},
                        description="检查根目录磁盘使用情况",
                    ),
                    TemplateStep(
                        worker="system",
                        action="find_large_files",
                        args={"path": "/var/log", "min_size_mb": 100},
                        description="查找 /var/log 下大于 100MB 的文件",
                    ),
                ],
            ),
            TaskTemplate(
                name="container_health_check",
                description="容器健康检查流程",
                category="container",
                steps=[
                    TemplateStep(
                        worker="container",
                        action="list_containers",
                        args={"all": False},
                        description="列出所有运行中的容器",
                    ),
                ],
            ),
            TaskTemplate(
                name="service_restart",
                description="服务重启标准流程（容器版）",
                category="container",
                steps=[
                    TemplateStep(
                        worker="container",
                        action="inspect_container",
                        args={"container_id": ""},
                        description="检查容器状态（需要指定 container_id）",
                    ),
                    TemplateStep(
                        worker="container",
                        action="restart",
                        args={"container_id": ""},
                        description="重启容器（需要指定 container_id）",
                    ),
                ],
            ),
            TaskTemplate(
                name="log_analysis",
                description="日志分析流程",
                category="troubleshooting",
                steps=[
                    TemplateStep(
                        worker="system",
                        action="find_large_files",
                        args={"path": "/var/log", "min_size_mb": 10},
                        description="查找大日志文件",
                    ),
                ],
            ),
        ]

        for template in default_templates:
            self.save_template(template)

    def save_template(self, template: TaskTemplate) -> None:
        """保存模板到文件

        Args:
            template: 模板对象
        """
        template_path = self._template_dir / f"{template.name}.json"
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(template.model_dump_json(indent=2))

    def load_template(self, name: str) -> Optional[TaskTemplate]:
        """加载模板

        Args:
            name: 模板名称

        Returns:
            模板对象，不存在返回 None
        """
        template_path = self._template_dir / f"{name}.json"
        if not template_path.exists():
            return None

        try:
            with open(template_path, encoding="utf-8") as f:
                data = json.load(f)
            return TaskTemplate.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return None

    def list_templates(self) -> list[TaskTemplate]:
        """列出所有模板

        Returns:
            模板列表
        """
        templates: list[TaskTemplate] = []
        for template_path in self._template_dir.glob("*.json"):
            template = self.load_template(template_path.stem)
            if template:
                templates.append(template)
        return templates

    def delete_template(self, name: str) -> bool:
        """删除模板

        Args:
            name: 模板名称

        Returns:
            是否删除成功
        """
        template_path = self._template_dir / f"{name}.json"
        if template_path.exists():
            template_path.unlink()
            return True
        return False

    def generate_instructions(
        self,
        template: TaskTemplate,
        context: Optional[dict[str, ArgValue]] = None,
    ) -> list[Instruction]:
        """从模板生成指令列表

        Args:
            template: 模板对象
            context: 上下文变量，用于替换模板中的占位符

        Returns:
            指令列表
        """
        instructions: list[Instruction] = []
        context = context or {}

        for step in template.steps:
            # 替换参数中的占位符
            args = self._replace_placeholders(step.args, context)

            instruction = Instruction(
                worker=step.worker,
                action=step.action,
                args=args,
            )
            instructions.append(instruction)

        return instructions

    def _replace_placeholders(
        self,
        args: dict[str, ArgValue],
        context: dict[str, ArgValue],
    ) -> dict[str, ArgValue]:
        """替换参数中的占位符

        Args:
            args: 原始参数
            context: 上下文变量

        Returns:
            替换后的参数
        """
        result: dict[str, ArgValue] = {}

        for key, value in args.items():
            if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                # 提取变量名
                var_name = value[2:-2].strip()
                # 从上下文中获取值
                result[key] = context.get(var_name, value)
            else:
                result[key] = value

        return result
