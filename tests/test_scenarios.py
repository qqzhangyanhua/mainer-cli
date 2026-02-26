"""场景推荐系统测试"""

from __future__ import annotations

import pytest

from src.context.detector import EnvironmentInfo
from src.orchestrator.scenarios import (
    SCENARIOS,
    Scenario,
    ScenarioManager,
    ScenarioStep,
)


class TestScenarioStep:
    """测试 ScenarioStep 数据类"""

    def test_create_step(self) -> None:
        """测试创建场景步骤"""
        step = ScenarioStep(prompt="查看容器", description="检查服务状态")

        assert step.prompt == "查看容器"
        assert step.description == "检查服务状态"


class TestScenario:
    """测试 Scenario 数据类"""

    def test_create_scenario(self) -> None:
        """测试创建场景"""
        scenario = Scenario(
            id="test_scenario",
            title="测试场景",
            description="这是一个测试场景",
            category="testing",
            icon="🧪",
            steps=[
                ScenarioStep(prompt="步骤1", description="第一步"),
                ScenarioStep(prompt="步骤2", description="第二步"),
            ],
            risk_level="safe",
            tags=["测试", "示例"],
        )

        assert scenario.id == "test_scenario"
        assert scenario.title == "测试场景"
        assert scenario.category == "testing"
        assert len(scenario.steps) == 2
        assert scenario.risk_level == "safe"
        assert "测试" in scenario.tags


class TestScenarioManager:
    """测试 ScenarioManager"""

    @pytest.fixture
    def manager(self) -> ScenarioManager:
        """创建场景管理器"""
        return ScenarioManager()

    def test_get_all_scenarios(self, manager: ScenarioManager) -> None:
        """测试获取所有场景"""
        scenarios = manager.get_all()

        assert len(scenarios) > 0
        assert all(isinstance(s, Scenario) for s in scenarios)

    def test_get_by_id_exists(self, manager: ScenarioManager) -> None:
        """测试通过 ID 获取场景（存在）"""
        scenario = manager.get_by_id("disk_full")

        assert scenario is not None
        assert scenario.id == "disk_full"
        assert scenario.title == "磁盘空间不足"

    def test_get_by_id_not_exists(self, manager: ScenarioManager) -> None:
        """测试通过 ID 获取场景（不存在）"""
        scenario = manager.get_by_id("nonexistent")

        assert scenario is None

    def test_get_by_category(self, manager: ScenarioManager) -> None:
        """测试按分类获取场景"""
        troubleshooting = manager.get_by_category("troubleshooting")

        assert len(troubleshooting) > 0
        assert all(s.category == "troubleshooting" for s in troubleshooting)

    def test_get_by_category_empty(self, manager: ScenarioManager) -> None:
        """测试按分类获取场景（空分类）"""
        scenarios = manager.get_by_category("nonexistent_category")

        assert scenarios == []

    def test_search_by_title(self, manager: ScenarioManager) -> None:
        """测试按标题搜索"""
        results = manager.search("磁盘")

        assert len(results) > 0
        assert any("磁盘" in s.title for s in results)

    def test_search_by_description(self, manager: ScenarioManager) -> None:
        """测试按描述搜索"""
        results = manager.search("清理")

        assert len(results) > 0

    def test_search_by_tag(self, manager: ScenarioManager) -> None:
        """测试按标签搜索"""
        results = manager.search("docker")

        assert len(results) > 0
        assert any("docker" in s.tags for s in results)

    def test_search_no_results(self, manager: ScenarioManager) -> None:
        """测试搜索无结果"""
        results = manager.search("zzzznonexistent")

        assert results == []


class TestScenarioRecommendation:
    """测试场景推荐"""

    @pytest.fixture
    def manager(self) -> ScenarioManager:
        """创建场景管理器"""
        return ScenarioManager()

    def test_recommend_with_high_disk_usage(self, manager: ScenarioManager) -> None:
        """测试高磁盘使用时推荐"""
        env_info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=85.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        recommendations = manager.recommend(env_info)

        assert len(recommendations) > 0
        assert any(s.id == "disk_full" for s in recommendations)

    def test_recommend_with_high_memory_usage(self, manager: ScenarioManager) -> None:
        """测试高内存使用时推荐"""
        env_info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=85.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        recommendations = manager.recommend(env_info)

        assert len(recommendations) > 0
        assert any(s.id == "high_memory" for s in recommendations)

    def test_recommend_with_docker_containers(self, manager: ScenarioManager) -> None:
        """测试有 Docker 容器时推荐"""
        env_info = EnvironmentInfo(
            has_docker=True,
            docker_containers=5,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        recommendations = manager.recommend(env_info)

        assert len(recommendations) > 0
        assert any(s.id == "service_down" for s in recommendations)
        assert any(s.id == "check_logs" for s in recommendations)

    def test_recommend_default(self, manager: ScenarioManager) -> None:
        """测试默认推荐"""
        env_info = EnvironmentInfo(
            has_docker=False,
            docker_containers=0,
            has_systemd=False,
            systemd_services=[],
            has_kubernetes=False,
            disk_usage=50.0,
            memory_usage=50.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        recommendations = manager.recommend(env_info)

        assert len(recommendations) > 0
        # 默认应该推荐查看日志或部署项目
        assert any(s.id in ["check_logs", "deploy_github"] for s in recommendations)

    def test_recommend_max_count(self, manager: ScenarioManager) -> None:
        """测试推荐数量上限"""
        env_info = EnvironmentInfo(
            has_docker=True,
            docker_containers=10,
            has_systemd=True,
            systemd_services=["nginx", "mysql"],
            has_kubernetes=True,
            disk_usage=90.0,
            memory_usage=90.0,
            os_type="Linux",
            os_version="5.15.0",
        )

        recommendations = manager.recommend(env_info)

        assert len(recommendations) <= 5


class TestPredefinedScenarios:
    """测试预置场景"""

    def test_all_scenarios_have_required_fields(self) -> None:
        """测试所有场景都有必填字段"""
        for scenario in SCENARIOS:
            assert scenario.id, "场景缺少 ID"
            assert scenario.title, f"场景 {scenario.id} 缺少标题"
            assert scenario.description, f"场景 {scenario.id} 缺少描述"
            assert scenario.category, f"场景 {scenario.id} 缺少分类"
            assert scenario.icon, f"场景 {scenario.id} 缺少图标"
            assert len(scenario.steps) > 0, f"场景 {scenario.id} 缺少步骤"

    def test_all_scenarios_have_valid_risk_level(self) -> None:
        """测试所有场景都有有效的风险等级"""
        valid_levels = {"safe", "medium", "high"}
        for scenario in SCENARIOS:
            assert scenario.risk_level in valid_levels, (
                f"场景 {scenario.id} 的风险等级 '{scenario.risk_level}' 无效"
            )

    def test_all_scenarios_have_valid_category(self) -> None:
        """测试所有场景都有有效的分类"""
        valid_categories = {"troubleshooting", "maintenance", "deployment", "monitoring"}
        for scenario in SCENARIOS:
            assert scenario.category in valid_categories, (
                f"场景 {scenario.id} 的分类 '{scenario.category}' 无效"
            )

    def test_scenario_ids_are_unique(self) -> None:
        """测试场景 ID 唯一"""
        ids = [s.id for s in SCENARIOS]
        assert len(ids) == len(set(ids)), "存在重复的场景 ID"


class TestFormatScenarioList:
    """测试场景列表格式化"""

    @pytest.fixture
    def manager(self) -> ScenarioManager:
        """创建场景管理器"""
        return ScenarioManager()

    def test_format_all_scenarios(self, manager: ScenarioManager) -> None:
        """测试格式化所有场景"""
        output = manager.format_scenario_list()

        assert "常见运维场景" in output
        assert "故障排查" in output
        assert "日常维护" in output
        assert "项目部署" in output
        assert "监控查看" in output

    def test_format_subset_scenarios(self, manager: ScenarioManager) -> None:
        """测试格式化部分场景"""
        scenarios = manager.get_by_category("troubleshooting")
        output = manager.format_scenario_list(scenarios)

        assert "故障排查" in output
        # 其他分类不应出现（因为没有该分类的场景）
