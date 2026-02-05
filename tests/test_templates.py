"""模板系统测试"""

import tempfile
from pathlib import Path

import pytest

from src.templates import TaskTemplate, TemplateManager, TemplateStep
from src.types import Instruction


class TestTemplateManager:
    """TemplateManager 测试类"""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_dir: Path) -> TemplateManager:
        """创建 TemplateManager 实例"""
        return TemplateManager(temp_dir)

    def test_create_default_templates(self, manager: TemplateManager) -> None:
        """测试创建默认模板"""
        templates = manager.list_templates()
        assert len(templates) > 0

        template_names = [t.name for t in templates]
        assert "disk_cleanup" in template_names
        assert "container_health_check" in template_names

    def test_save_and_load_template(self, manager: TemplateManager) -> None:
        """测试保存和加载模板"""
        template = TaskTemplate(
            name="test_template",
            description="Test template",
            category="test",
            steps=[
                TemplateStep(
                    worker="system",
                    action="check_disk_usage",
                    args={"path": "/"},
                    description="Check disk",
                ),
            ],
        )

        manager.save_template(template)
        loaded = manager.load_template("test_template")

        assert loaded is not None
        assert loaded.name == "test_template"
        assert loaded.description == "Test template"
        assert len(loaded.steps) == 1

    def test_delete_template(self, manager: TemplateManager) -> None:
        """测试删除模板"""
        template = TaskTemplate(
            name="to_delete",
            description="Will be deleted",
            category="test",
            steps=[],
        )

        manager.save_template(template)
        assert manager.load_template("to_delete") is not None

        result = manager.delete_template("to_delete")
        assert result is True
        assert manager.load_template("to_delete") is None

    def test_generate_instructions(self, manager: TemplateManager) -> None:
        """测试生成指令"""
        template = TaskTemplate(
            name="test",
            description="Test",
            category="test",
            steps=[
                TemplateStep(
                    worker="system",
                    action="check_disk_usage",
                    args={"path": "/"},
                ),
                TemplateStep(
                    worker="system",
                    action="find_large_files",
                    args={"path": "/var/log", "min_size_mb": 100},
                ),
            ],
        )

        instructions = manager.generate_instructions(template)

        assert len(instructions) == 2
        assert isinstance(instructions[0], Instruction)
        assert instructions[0].worker == "system"
        assert instructions[0].action == "check_disk_usage"
        assert instructions[1].action == "find_large_files"

    def test_generate_instructions_with_context(self, manager: TemplateManager) -> None:
        """测试使用上下文生成指令"""
        template = TaskTemplate(
            name="test",
            description="Test",
            category="test",
            steps=[
                TemplateStep(
                    worker="container",
                    action="restart",
                    args={"container_id": "{{ container_id }}"},
                ),
            ],
        )

        context = {"container_id": "my-app"}
        instructions = manager.generate_instructions(template, context)

        assert len(instructions) == 1
        assert instructions[0].args["container_id"] == "my-app"
