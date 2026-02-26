"""场景推荐系统

预置常见运维场景，根据环境自动推荐适合的操作流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.context.detector import EnvironmentInfo


@dataclass
class ScenarioStep:
    """场景步骤"""

    prompt: str
    description: str


@dataclass
class Scenario:
    """运维场景"""

    id: str
    title: str
    description: str
    category: str  # troubleshooting, maintenance, deployment, monitoring
    icon: str
    steps: list[ScenarioStep]
    risk_level: str = "safe"  # safe, medium, high
    tags: list[str] = field(default_factory=list)


# 预置场景库
SCENARIOS: list[Scenario] = [
    # 故障排查
    Scenario(
        id="service_down",
        title="服务无响应",
        description="网站/API 打不开，快速诊断和修复",
        category="troubleshooting",
        icon="🔴",
        steps=[
            ScenarioStep(prompt="列出所有容器", description="检查服务是否运行"),
            ScenarioStep(prompt="查看日志", description="查找错误信息"),
            ScenarioStep(prompt="重启服务", description="尝试恢复服务"),
        ],
        risk_level="medium",
        tags=["docker", "服务", "网站", "API"],
    ),
    Scenario(
        id="high_cpu",
        title="CPU 占用过高",
        description="排查资源占用，优化性能",
        category="troubleshooting",
        icon="🔥",
        steps=[
            ScenarioStep(prompt="查看进程 CPU 占用", description="找出占用最高的进程"),
            ScenarioStep(prompt="分析进程详情", description="了解进程用途"),
            ScenarioStep(prompt="重启高占用服务", description="尝试恢复正常"),
        ],
        risk_level="medium",
        tags=["CPU", "性能", "进程"],
    ),
    Scenario(
        id="high_memory",
        title="内存占用过高",
        description="排查内存泄漏，释放资源",
        category="troubleshooting",
        icon="💧",
        steps=[
            ScenarioStep(prompt="查看内存占用", description="找出占用最高的进程"),
            ScenarioStep(prompt="分析进程详情", description="判断是否正常"),
            ScenarioStep(prompt="重启服务释放内存", description="尝试恢复正常"),
        ],
        risk_level="medium",
        tags=["内存", "性能", "泄漏"],
    ),
    # 日常维护
    Scenario(
        id="disk_full",
        title="磁盘空间不足",
        description="清理大文件和日志，释放磁盘空间",
        category="maintenance",
        icon="💾",
        steps=[
            ScenarioStep(prompt="查看磁盘使用情况", description="定位占用高的目录"),
            ScenarioStep(prompt="查找大文件", description="找出可清理的文件"),
            ScenarioStep(prompt="清理日志", description="删除旧日志文件"),
        ],
        risk_level="medium",
        tags=["磁盘", "清理", "空间"],
    ),
    Scenario(
        id="clean_docker",
        title="清理 Docker 资源",
        description="删除无用镜像和容器，释放空间",
        category="maintenance",
        icon="🐳",
        steps=[
            ScenarioStep(prompt="列出所有容器", description="查看容器状态"),
            ScenarioStep(prompt="删除停止的容器", description="清理无用容器"),
            ScenarioStep(prompt="删除无用镜像", description="释放磁盘空间"),
        ],
        risk_level="medium",
        tags=["docker", "清理", "镜像"],
    ),
    # 项目部署
    Scenario(
        id="deploy_github",
        title="部署 GitHub 项目",
        description="一键部署开源项目到服务器",
        category="deployment",
        icon="🚀",
        steps=[
            ScenarioStep(prompt="部署项目", description="自动克隆、配置、启动"),
        ],
        risk_level="medium",
        tags=["github", "部署", "开源"],
    ),
    Scenario(
        id="update_service",
        title="更新服务版本",
        description="拉取最新代码并重启服务",
        category="deployment",
        icon="🔄",
        steps=[
            ScenarioStep(prompt="拉取最新代码", description="git pull 更新代码"),
            ScenarioStep(prompt="重新构建", description="重建镜像或重新安装依赖"),
            ScenarioStep(prompt="重启服务", description="应用更新"),
        ],
        risk_level="medium",
        tags=["更新", "部署", "git"],
    ),
    # 监控查看
    Scenario(
        id="check_logs",
        title="查看服务日志",
        description="快速定位错误和异常",
        category="monitoring",
        icon="📋",
        steps=[
            ScenarioStep(prompt="列出所有服务", description="选择要查看的服务"),
            ScenarioStep(prompt="查看日志", description="显示最近的日志"),
        ],
        risk_level="safe",
        tags=["日志", "监控", "错误"],
    ),
    Scenario(
        id="check_status",
        title="检查系统状态",
        description="全面检查系统健康度",
        category="monitoring",
        icon="📊",
        steps=[
            ScenarioStep(prompt="系统资源快照", description="CPU、内存、磁盘、负载一览"),
            ScenarioStep(prompt="查看服务状态", description="检查关键服务"),
            ScenarioStep(prompt="查看网络连接", description="检查端口和连接"),
        ],
        risk_level="safe",
        tags=["状态", "监控", "健康"],
    ),
]


class ScenarioManager:
    """场景管理器

    提供场景查询、分类和推荐功能。
    """

    # 分类名称映射
    CATEGORY_NAMES = {
        "troubleshooting": "🔴 故障排查",
        "maintenance": "🛠️  日常维护",
        "deployment": "🚀 项目部署",
        "monitoring": "📊 监控查看",
    }

    def __init__(self) -> None:
        """初始化场景管理器"""
        self._scenarios = {s.id: s for s in SCENARIOS}

    def get_by_id(self, scenario_id: str) -> Optional[Scenario]:
        """根据 ID 获取场景

        Args:
            scenario_id: 场景 ID

        Returns:
            场景对象，不存在返回 None
        """
        return self._scenarios.get(scenario_id)

    def get_by_category(self, category: str) -> list[Scenario]:
        """根据分类获取场景

        Args:
            category: 分类名称

        Returns:
            该分类下的所有场景
        """
        return [s for s in SCENARIOS if s.category == category]

    def get_all(self) -> list[Scenario]:
        """获取所有场景

        Returns:
            所有场景列表
        """
        return SCENARIOS.copy()

    def search(self, query: str) -> list[Scenario]:
        """搜索场景

        Args:
            query: 搜索关键词

        Returns:
            匹配的场景列表
        """
        query_lower = query.lower()
        results: list[Scenario] = []

        for scenario in SCENARIOS:
            # 搜索标题、描述和标签
            if (
                query_lower in scenario.title.lower()
                or query_lower in scenario.description.lower()
                or any(query_lower in tag.lower() for tag in scenario.tags)
            ):
                results.append(scenario)

        return results

    def recommend(self, env_info: EnvironmentInfo) -> list[Scenario]:
        """根据环境推荐场景

        Args:
            env_info: 环境信息

        Returns:
            推荐的场景列表
        """
        recommendations: list[Scenario] = []

        # 磁盘告警 → 推荐清理场景
        if env_info.disk_usage > 80:
            disk_scenario = self.get_by_id("disk_full")
            if disk_scenario:
                recommendations.append(disk_scenario)

        # 内存告警 → 推荐内存排查
        if env_info.memory_usage > 80:
            memory_scenario = self.get_by_id("high_memory")
            if memory_scenario:
                recommendations.append(memory_scenario)

        # 有 Docker 容器 → 推荐服务管理
        if env_info.has_docker and env_info.docker_containers > 0:
            service_scenario = self.get_by_id("service_down")
            logs_scenario = self.get_by_id("check_logs")
            if service_scenario:
                recommendations.append(service_scenario)
            if logs_scenario:
                recommendations.append(logs_scenario)

        # 有 Kubernetes → 推荐状态检查
        if env_info.has_kubernetes:
            status_scenario = self.get_by_id("check_status")
            if status_scenario:
                recommendations.append(status_scenario)

        # 默认推荐
        if not recommendations:
            logs_scenario = self.get_by_id("check_logs")
            deploy_scenario = self.get_by_id("deploy_github")
            if logs_scenario:
                recommendations.append(logs_scenario)
            if deploy_scenario:
                recommendations.append(deploy_scenario)

        # 去重（保持顺序）
        seen = set()
        unique_recommendations: list[Scenario] = []
        for s in recommendations:
            if s.id not in seen:
                seen.add(s.id)
                unique_recommendations.append(s)

        return unique_recommendations[:5]  # 最多返回 5 个

    def format_scenario_list(self, scenarios: Optional[list[Scenario]] = None) -> str:
        """格式化场景列表为显示字符串

        Args:
            scenarios: 要格式化的场景列表，None 则显示全部

        Returns:
            格式化后的字符串
        """
        if scenarios is None:
            scenarios = self.get_all()

        lines: list[str] = ["常见运维场景", ""]

        # 按分类组织
        for cat_id, cat_name in self.CATEGORY_NAMES.items():
            cat_scenarios = [s for s in scenarios if s.category == cat_id]
            if not cat_scenarios:
                continue

            lines.append(cat_name)
            for scenario in cat_scenarios:
                risk_badge = {
                    "safe": "[安全]",
                    "medium": "[中等]",
                    "high": "[高危]",
                }.get(scenario.risk_level, "")

                lines.append(f"  {scenario.icon} {scenario.title} {risk_badge}")
                lines.append(f"      ID: {scenario.id}")
                lines.append(f"      {scenario.description}")
            lines.append("")

        lines.extend(
            [
                "使用方法：",
                "  - 输入 /scenario <ID> 执行场景",
                "  - 或直接描述你的问题（如 '服务打不开'）",
            ]
        )

        return "\n".join(lines)
