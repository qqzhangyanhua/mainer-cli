# OpsAI 核心重构方案 (v0.4.0)

**日期**: 2026-02-26  
**目标**: 提升用户体验和架构稳定性  
**预计工期**: 2-3 周

---

## 目录

- [P0-1: 首次运行引导系统](#p0-1-首次运行引导系统)
- [P0-2: 命令模式匹配 Fallback](#p0-2-命令模式匹配-fallback)
- [P0-3: Worker 插件化架构](#p0-3-worker-插件化架构)
- [P0-4: Token 预算与成本控制](#p0-4-token-预算与成本控制)
- [P1-1: ErrorHelper 智能错误提示](#p1-1-errorhelper-智能错误提示)
- [P1-2: 场景推荐系统集成](#p1-2-场景推荐系统集成)
- [P1-3: 结构化日志系统](#p1-3-结构化日志系统)

---

## P0-1: 首次运行引导系统

### 📊 当前问题

1. **用户首次启动后迷茫**: 不知道 OpsAI 能做什么
2. **学习曲线陡峭**: 需要阅读长文档才能上手
3. **价值展示延迟**: 用户无法在 30 秒内看到实际效果

### 🎯 设计目标

- 首次启动自动触发引导流程
- 检测用户环境（Docker/Systemd/K8s）
- 提供 3 个可点击的示例命令
- 允许用户跳过引导

### 📐 架构设计

```
┌─────────────────────────────────────────┐
│        FirstRunWizard (Widget)          │
├─────────────────────────────────────────┤
│  1. 检测环境 (EnvironmentDetector)      │
│  2. 生成推荐命令                         │
│  3. 可交互执行                           │
│  4. 标记已完成 (~/.opsai/first_run)     │
└─────────────────────────────────────────┘
```

### 💻 代码实现

#### 1. 新建引导 Widget

```python
# src/tui/widgets/first_run_wizard.py
from __future__ import annotations

from pathlib import Path
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Button, Label, Static
from textual.message import Message

from src.context.detector import EnvironmentDetector


class FirstRunWizard(Container):
    """首次运行引导向导"""

    DEFAULT_CSS = """
    FirstRunWizard {
        width: 80;
        height: auto;
        padding: 2;
        border: heavy $primary;
        background: $panel;
        align: center middle;
        layer: overlay;
    }

    FirstRunWizard .title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
    }

    FirstRunWizard .section {
        width: 100%;
        padding: 1 0;
    }

    FirstRunWizard .command-btn {
        width: 100%;
        margin: 1 0;
    }

    FirstRunWizard .skip-btn {
        width: 20;
        margin: 1 auto;
    }
    """

    class CommandClicked(Message):
        """用户点击了推荐命令"""

        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    class Dismissed(Message):
        """引导被关闭"""

        pass

    def __init__(self) -> None:
        super().__init__()
        self.detector = EnvironmentDetector()

    def compose(self) -> ComposeResult:
        env_info = self.detector.detect()

        with Vertical():
            yield Label("🎉 欢迎使用 OpsAI", classes="title")
            yield Static("")

            # 环境检测结果
            env_lines = ["检测到你的环境:"]
            if env_info.has_docker:
                containers = env_info.docker_info.get("container_count", 0)
                env_lines.append(f"  ✓ Docker ({containers} 个容器)")
            if env_info.has_systemd:
                env_lines.append("  ✓ Systemd 服务管理器")
            if env_info.has_kubernetes:
                env_lines.append("  ✓ Kubernetes 集群")

            yield Static("\n".join(env_lines), classes="section")
            yield Static("")

            # 推荐命令
            yield Label("试试这些操作:", classes="section")
            recommendations = self._generate_recommendations(env_info)
            for idx, (label, command) in enumerate(recommendations, 1):
                yield Button(f"{idx}️⃣  {label}", id=f"cmd-{idx}", classes="command-btn")

            yield Static("")
            yield Button("稍后再说", id="skip", classes="skip-btn")

    def _generate_recommendations(self, env_info) -> list[tuple[str, str]]:
        """根据环境生成推荐命令"""
        recommendations = []

        if env_info.has_docker:
            recommendations.append(("查看所有容器", "查看所有容器"))
        else:
            recommendations.append(("查看系统进程", "查看占用最高的5个进程"))

        # 磁盘检查（通用）
        recommendations.append(("检查磁盘空间", "查看磁盘使用情况"))

        # 监控（通用）
        recommendations.append(("查看系统负载", "查看系统资源状态"))

        return recommendations[:3]

    @on(Button.Pressed, "#cmd-1, #cmd-2, #cmd-3")
    def on_command_click(self, event: Button.Pressed) -> None:
        """处理命令按钮点击"""
        idx = int(event.button.id.split("-")[1])
        env_info = self.detector.detect()
        recommendations = self._generate_recommendations(env_info)
        command = recommendations[idx - 1][1]

        self.post_message(self.CommandClicked(command))
        self._mark_completed()
        self.remove()

    @on(Button.Pressed, "#skip")
    def on_skip_click(self) -> None:
        """跳过引导"""
        self._mark_completed()
        self.post_message(self.Dismissed())
        self.remove()

    @staticmethod
    def _mark_completed() -> None:
        """标记引导已完成"""
        marker = Path.home() / ".opsai" / "first_run"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    @staticmethod
    def should_show() -> bool:
        """检查是否应该显示引导"""
        marker = Path.home() / ".opsai" / "first_run"
        return not marker.exists()
```

#### 2. 集成到 TUI App

```python
# src/tui/app.py (修改)

from src.tui.widgets import FirstRunWizard  # 新增导入

class OpsAIApp(App[str]):
    # ... 现有代码 ...

    def on_mount(self) -> None:
        """挂载时触发"""
        # 原有的初始化代码
        # ...

        # 首次运行检查
        if FirstRunWizard.should_show():
            self.show_first_run_wizard()

    def show_first_run_wizard(self) -> None:
        """显示首次运行引导"""
        wizard = FirstRunWizard()
        self.mount(wizard)

    @on(FirstRunWizard.CommandClicked)
    def on_wizard_command(self, event: FirstRunWizard.CommandClicked) -> None:
        """处理引导命令点击"""
        self.query_one("#user-input", Input).value = event.command
        # 自动提交
        self._submit_input()

    @on(FirstRunWizard.Dismissed)
    def on_wizard_dismissed(self) -> None:
        """引导被关闭"""
        self.notify("你随时可以输入 /help 查看帮助")
```

#### 3. 环境检测器增强

```python
# src/context/detector.py (新增方法)

class EnvironmentDetector:
    # ... 现有代码 ...

    def detect(self) -> EnvironmentInfo:
        """检测环境信息（缓存结果）"""
        if hasattr(self, "_cached_info"):
            return self._cached_info

        info = EnvironmentInfo(
            has_docker=self.detect_docker(),
            has_systemd=self.detect_systemd(),
            has_kubernetes=self.detect_kubernetes(),
            docker_info=self._get_docker_info() if self.detect_docker() else {},
        )
        self._cached_info = info
        return info

    def _get_docker_info(self) -> dict:
        """获取 Docker 详细信息"""
        try:
            result = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            container_count = len([l for l in result.stdout.strip().split("\n") if l])
            return {"container_count": container_count}
        except Exception:
            return {}


@dataclass
class EnvironmentInfo:
    has_docker: bool
    has_systemd: bool
    has_kubernetes: bool
    docker_info: dict
```

### 🧪 测试策略

```python
# tests/test_first_run_wizard.py

from pathlib import Path
import pytest
from textual.pilot import Pilot
from src.tui.widgets import FirstRunWizard


@pytest.fixture
def mock_first_run(tmp_path, monkeypatch):
    """Mock 首次运行标记文件"""
    marker = tmp_path / "first_run"
    monkeypatch.setattr(
        FirstRunWizard, "_get_marker_path", lambda: marker
    )
    return marker


async def test_wizard_shows_on_first_run(mock_first_run):
    """首次运行时显示引导"""
    assert FirstRunWizard.should_show() is True


async def test_wizard_hides_after_completion(mock_first_run):
    """完成后不再显示"""
    FirstRunWizard._mark_completed()
    assert FirstRunWizard.should_show() is False


async def test_wizard_docker_recommendations():
    """Docker 环境推荐 Docker 命令"""
    wizard = FirstRunWizard()
    env_info = EnvironmentInfo(has_docker=True, has_systemd=False)
    recs = wizard._generate_recommendations(env_info)
    assert any("容器" in label for label, _ in recs)


async def test_wizard_command_click(app):
    """点击命令触发事件"""
    async with app.run_test() as pilot:
        wizard = FirstRunWizard()
        app.mount(wizard)

        messages = []
        wizard.on_message = lambda m: messages.append(m)

        await pilot.click("#cmd-1")
        assert any(isinstance(m, FirstRunWizard.CommandClicked) for m in messages)
```

### 📈 成功指标

- 显示引导的用户中，80% 点击至少 1 个推荐命令
- 首次成功操作时间 < 2 分钟
- 跳过率 < 30%

### 🔄 迁移路径

1. **Phase 1** (Week 1, Day 1-2): 实现 Widget 和环境检测
2. **Phase 2** (Week 1, Day 3): 集成到 TUI App
3. **Phase 3** (Week 1, Day 4): 测试和优化

---

## P0-2: 命令模式匹配 Fallback

### 📊 当前问题

1. **LLM 依赖过重**: 每个请求都需要调用 LLM，延迟高
2. **成本高**: 简单命令（如"查看容器"）消耗不必要的 Token
3. **无离线能力**: LLM 不可用时系统完全瘫痪
4. **响应速度慢**: 简单查询也需要 2-3 秒

### 🎯 设计目标

- 70% 的常见命令通过规则引擎处理（< 0.5s）
- LLM 只处理复杂/模糊意图
- 支持离线模式
- 保持现有 API 兼容性

### 📐 架构设计

```
用户输入
    │
    v
┌─────────────────────────────┐
│  CommandCache (规则匹配)     │ ← 快速路径 (70% 命中)
├─────────────────────────────┤
│  - 精确匹配                  │
│  - 正则模式                  │
│  - 参数提取                  │
└─────────────────────────────┘
    │ (未匹配)
    v
┌─────────────────────────────┐
│  LLM Reasoning              │ ← 慢速路径 (30%)
└─────────────────────────────┘
```

### 💻 代码实现

#### 1. 命令缓存引擎

```python
# src/orchestrator/command_cache.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.types import Instruction


@dataclass
class CommandPattern:
    """命令模式定义"""

    pattern: str  # 正则表达式
    worker: str
    action: str
    args_extractor: Optional[callable] = None  # 参数提取函数
    confidence: float = 0.9  # 匹配置信度


class CommandCache:
    """命令缓存与模式匹配引擎"""

    # 预定义的高频命令模式
    PATTERNS: list[CommandPattern] = [
        # 容器相关
        CommandPattern(
            pattern=r"^(查看|列出|显示)(所有)?容器$",
            worker="container",
            action="list",
        ),
        CommandPattern(
            pattern=r"^重启\s*(?P<container_id>[\w\-]+)(?:\s*容器)?$",
            worker="container",
            action="restart",
            args_extractor=lambda m: {"container_id": m.group("container_id")},
        ),
        CommandPattern(
            pattern=r"^(查看|显示)(?P<container_id>[\w\-]+)(的)?日志$",
            worker="container",
            action="get_logs",
            args_extractor=lambda m: {
                "container_id": m.group("container_id"),
                "lines": 50,
            },
        ),
        # 系统相关
        CommandPattern(
            pattern=r"^(查看|检查)(磁盘|硬盘)(使用|空间)(情况)?$",
            worker="system",
            action="check_disk",
        ),
        CommandPattern(
            pattern=r"^(查找|查询)(大|超过)\s*(\d+)(MB|GB)\s*(的)?文件$",
            worker="system",
            action="find_large_files",
            args_extractor=lambda m: {
                "path": "/",
                "size_mb": int(m.group(3)) * (1024 if m.group(4) == "GB" else 1),
            },
        ),
        # 监控相关
        CommandPattern(
            pattern=r"^(查看|显示)(系统)?(资源|状态|负载)$",
            worker="monitor",
            action="snapshot",
        ),
        CommandPattern(
            pattern=r"^(检查|查看)(?P<port>\d+)\s*端口(是否)?(开放|监听)$",
            worker="monitor",
            action="check_port",
            args_extractor=lambda m: {"port": int(m.group("port"))},
        ),
        # Git 相关
        CommandPattern(
            pattern=r"^(查看|显示)git\s*(状态|status)$",
            worker="git",
            action="status",
        ),
        CommandPattern(
            pattern=r"^拉取(最新)?(代码|更新)$",
            worker="git",
            action="pull",
        ),
    ]

    def __init__(self) -> None:
        self._compiled_patterns = [
            (re.compile(p.pattern, re.IGNORECASE), p) for p in self.PATTERNS
        ]
        self._hit_count: dict[str, int] = {}  # 统计命中次数

    def match(self, user_input: str) -> Optional[tuple[Instruction, float]]:
        """尝试匹配用户输入

        Returns:
            (Instruction, confidence) 或 None
        """
        user_input = user_input.strip()

        for regex, pattern in self._compiled_patterns:
            match = regex.match(user_input)
            if match:
                # 提取参数
                args = {}
                if pattern.args_extractor:
                    args = pattern.args_extractor(match)

                instruction = Instruction(
                    worker=pattern.worker,
                    action=pattern.action,
                    args=args,
                    risk_level="safe",  # 预定义模式默认安全
                    dry_run=False,
                )

                # 统计
                key = f"{pattern.worker}.{pattern.action}"
                self._hit_count[key] = self._hit_count.get(key, 0) + 1

                return instruction, pattern.confidence

        return None

    def get_stats(self) -> dict[str, int]:
        """获取匹配统计"""
        return self._hit_count.copy()

    def add_pattern(self, pattern: CommandPattern) -> None:
        """动态添加新模式（用于学习）"""
        self.PATTERNS.append(pattern)
        self._compiled_patterns.append((re.compile(pattern.pattern), pattern))
```

#### 2. 集成到 OrchestratorEngine

```python
# src/orchestrator/engine.py (修改)

from src.orchestrator.command_cache import CommandCache

class OrchestratorEngine:
    def __init__(self, config: OpsAIConfig, ...) -> None:
        # ... 现有代码 ...
        self._command_cache = CommandCache()  # 新增
        self._cache_enabled = config.performance.get("enable_command_cache", True)

    async def process(
        self,
        user_request: str,
        history: list[ConversationEntry] | None = None,
    ) -> WorkerResult:
        """处理用户请求"""
        history = history or []

        # 1. 尝试缓存匹配 (快速路径)
        if self._cache_enabled:
            cached = self._command_cache.match(user_request)
            if cached:
                instruction, confidence = cached
                self._emit_progress("cache_hit", f"命中缓存模式 (置信度: {confidence})")

                # 如果置信度高，直接执行
                if confidence > 0.85:
                    return await self._execute_instruction(instruction)

        # 2. LLM 推理 (慢速路径)
        self._emit_progress("llm_reasoning", "使用 LLM 分析意图...")
        # ... 原有的 LLM 处理逻辑 ...
```

#### 3. 配置支持

```python
# src/config/manager.py (新增)

class PerformanceConfig(BaseModel):
    """性能配置"""

    enable_command_cache: bool = True
    cache_confidence_threshold: float = 0.85
    max_cache_size: int = 1000


class OpsAIConfig(BaseModel):
    # ... 现有字段 ...
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
```

### 🧪 测试策略

```python
# tests/test_command_cache.py

import pytest
from src.orchestrator.command_cache import CommandCache, CommandPattern


def test_exact_match_container_list():
    """精确匹配: 查看容器"""
    cache = CommandCache()
    result = cache.match("查看容器")

    assert result is not None
    instruction, confidence = result
    assert instruction.worker == "container"
    assert instruction.action == "list"
    assert confidence > 0.8


def test_regex_match_with_args():
    """正则匹配: 重启 nginx"""
    cache = CommandCache()
    result = cache.match("重启 nginx")

    assert result is not None
    instruction, confidence = result
    assert instruction.worker == "container"
    assert instruction.action == "restart"
    assert instruction.args["container_id"] == "nginx"


def test_no_match_fallback_to_llm():
    """无匹配时返回 None"""
    cache = CommandCache()
    result = cache.match("这是一个复杂的未定义命令")
    assert result is None


@pytest.mark.asyncio
async def test_engine_uses_cache_first(mock_engine):
    """引擎优先使用缓存"""
    result = await mock_engine.process("查看容器")
    assert mock_engine._command_cache._hit_count["container.list"] == 1


def test_cache_stats_tracking():
    """统计命中次数"""
    cache = CommandCache()
    cache.match("查看容器")
    cache.match("查看容器")
    cache.match("检查磁盘空间")

    stats = cache.get_stats()
    assert stats["container.list"] == 2
    assert stats["system.check_disk"] == 1
```

### 📈 成功指标

- 缓存命中率 > 60%
- 缓存命中的响应时间 < 500ms
- LLM 调用减少 50%+
- Token 使用量减少 40%+

### 🔄 迁移路径

1. **Phase 1** (Week 1, Day 5): 实现 CommandCache 核心
2. **Phase 2** (Week 2, Day 1): 集成到 Engine (可选开关)
3. **Phase 3** (Week 2, Day 2): 添加 20+ 高频模式
4. **Phase 4** (Week 2, Day 3): A/B 测试和优化

---

## P0-3: Worker 插件化架构

### 📊 当前问题

1. **硬编码注册**: 所有 Workers 在 `engine.py` 中硬编码
2. **无法动态加载**: 不能在运行时启用/禁用 Worker
3. **启动开销大**: 加载不需要的 Workers（如 Kubernetes）
4. **不支持第三方插件**: 用户无法扩展自定义 Worker

### 🎯 设计目标

- 支持动态发现和注册 Workers
- 配置驱动的启用/禁用
- 插件热插拔（不重启）
- 第三方插件目录支持

### 📐 架构设计

```
┌────────────────────────────────────────┐
│         WorkerRegistry                 │
├────────────────────────────────────────┤
│  - discover_workers()                  │
│  - register_worker()                   │
│  - get_worker()                        │
│  - list_enabled()                      │
└────────────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│  Worker Discovery                       │
├─────────────────────────────────────────┤
│  1. 内置 Workers (src/workers/)         │
│  2. 插件目录 (~/.opsai/plugins/)        │
│  3. 配置过滤 (enabled/disabled)         │
└─────────────────────────────────────────┘
```

### 💻 代码实现

#### 1. Worker 注册中心

```python
# src/workers/registry.py
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Optional

from src.workers.base import BaseWorker


class WorkerRegistry:
    """Worker 注册与发现中心"""

    def __init__(self, enabled_workers: Optional[list[str]] = None) -> None:
        """初始化注册中心

        Args:
            enabled_workers: 启用的 Worker 名称列表，None 表示全部启用
        """
        self._workers: dict[str, BaseWorker] = {}
        self._enabled_workers = enabled_workers
        self._discovery_paths: list[Path] = []

    def discover_builtin_workers(self) -> None:
        """发现内置 Workers"""
        builtin_modules = [
            "system",
            "container",
            "compose",
            "shell",
            "monitor",
            "git",
            "http",
            "analyze",
            "deploy",
            "log_analyzer",
            "kubernetes",
            "remote",
            "notifier",
            "chat",
            "audit",
        ]

        for module_name in builtin_modules:
            # 检查是否启用
            if self._enabled_workers and module_name not in self._enabled_workers:
                continue

            try:
                self._load_worker_module(f"src.workers.{module_name}")
            except ImportError:
                # 可选依赖缺失，跳过
                continue

    def discover_plugin_workers(self, plugin_dir: Path) -> None:
        """发现插件 Workers

        插件结构:
        ~/.opsai/plugins/
            my_worker/
                __init__.py
                worker.py  (包含 MyWorker(BaseWorker))
        """
        if not plugin_dir.exists():
            return

        for plugin_path in plugin_dir.iterdir():
            if not plugin_path.is_dir() or plugin_path.name.startswith("_"):
                continue

            try:
                # 动态导入插件模块
                spec = importlib.util.spec_from_file_location(
                    f"plugins.{plugin_path.name}",
                    plugin_path / "__init__.py",
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # 查找 BaseWorker 子类
                    for name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and issubclass(obj, BaseWorker)
                            and obj is not BaseWorker
                        ):
                            worker = obj()
                            self.register(worker)
            except Exception as e:
                # 记录插件加载失败
                print(f"Failed to load plugin {plugin_path.name}: {e}")

    def _load_worker_module(self, module_path: str) -> None:
        """加载 Worker 模块并自动注册"""
        module = importlib.import_module(module_path)

        # 查找 Worker 类（按约定命名）
        for name, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseWorker)
                and obj is not BaseWorker
                and not name.startswith("_")
            ):
                # 实例化并注册
                try:
                    worker = obj()
                    self.register(worker)
                except Exception:
                    # Worker 可能需要额外参数，跳过
                    pass

    def register(self, worker: BaseWorker) -> None:
        """注册 Worker"""
        self._workers[worker.name] = worker

    def get(self, name: str) -> Optional[BaseWorker]:
        """获取 Worker"""
        return self._workers.get(name)

    def list_all(self) -> dict[str, BaseWorker]:
        """列出所有已注册的 Workers"""
        return self._workers.copy()

    def list_enabled(self) -> dict[str, BaseWorker]:
        """列出启用的 Workers"""
        if self._enabled_workers is None:
            return self.list_all()

        return {
            name: worker
            for name, worker in self._workers.items()
            if name in self._enabled_workers
        }

    def unregister(self, name: str) -> None:
        """注销 Worker（支持热插拔）"""
        self._workers.pop(name, None)
```

#### 2. 修改 OrchestratorEngine

```python
# src/orchestrator/engine.py (重构)

from src.workers.registry import WorkerRegistry

class OrchestratorEngine:
    def __init__(
        self,
        config: OpsAIConfig,
        confirmation_callback: Optional[Callable] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable] = None,
        use_sqlite_checkpoint: bool = False,
    ) -> None:
        """初始化引擎"""
        self._config = config
        self._llm_client = LLMClient(config.llm)
        self._context = EnvironmentContext()
        self._confirmation_callback = confirmation_callback
        self._dry_run = dry_run or config.safety.dry_run_by_default
        self._progress_callback = progress_callback

        # 使用 Worker 注册中心
        enabled_workers = config.workers.enabled if config.workers else None
        self._worker_registry = WorkerRegistry(enabled_workers)

        # 发现并注册 Workers
        self._worker_registry.discover_builtin_workers()

        # 发现插件 Workers
        plugin_dir = Path.home() / ".opsai" / "plugins"
        self._worker_registry.discover_plugin_workers(plugin_dir)

        # 特殊处理需要参数的 Workers
        self._register_special_workers()

    def _register_special_workers(self) -> None:
        """注册需要特殊参数的 Workers"""
        # AnalyzeWorker 需要 LLM 客户端
        if not self._worker_registry.get("analyze"):
            try:
                from src.workers.analyze import AnalyzeWorker
                self._worker_registry.register(AnalyzeWorker(self._llm_client))
            except ImportError:
                pass

        # AuditWorker 需要配置
        if not self._worker_registry.get("audit"):
            from src.workers.audit import AuditWorker
            audit_log_path = Path(self._config.audit.log_path).expanduser()
            self._worker_registry.register(
                AuditWorker(
                    log_path=audit_log_path,
                    max_log_size_mb=self._config.audit.max_log_size_mb,
                    retain_days=self._config.audit.retain_days,
                )
            )

    def get_worker(self, name: str) -> Optional[BaseWorker]:
        """获取 Worker"""
        return self._worker_registry.get(name)

    def list_workers(self) -> dict[str, BaseWorker]:
        """列出所有 Workers"""
        return self._worker_registry.list_enabled()
```

#### 3. 配置支持

```python
# src/config/manager.py (新增)

class WorkersConfig(BaseModel):
    """Workers 配置"""

    enabled: Optional[list[str]] = None  # None = 全部启用
    disabled: list[str] = Field(default_factory=list)
    plugin_dir: str = "~/.opsai/plugins"

    def is_enabled(self, worker_name: str) -> bool:
        """检查 Worker 是否启用"""
        if worker_name in self.disabled:
            return False
        if self.enabled is None:
            return True
        return worker_name in self.enabled


class OpsAIConfig(BaseModel):
    # ... 现有字段 ...
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
```

#### 4. CLI 命令支持

```python
# src/cli.py (新增)

@app.command()
def workers() -> None:
    """管理 Workers"""
    pass


@workers.command(name="list")
def list_workers() -> None:
    """列出所有可用的 Workers"""
    from rich.table import Table

    config = ConfigManager().load()
    engine = OrchestratorEngine(config)

    table = Table(title="Available Workers")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Capabilities", style="yellow")

    for name, worker in engine.list_workers().items():
        status = "✓ Enabled" if config.workers.is_enabled(name) else "✗ Disabled"
        caps = ", ".join(worker.get_capabilities())
        table.add_row(name, status, caps)

    console.print(table)


@workers.command(name="enable")
def enable_worker(name: str) -> None:
    """启用指定 Worker"""
    config_mgr = ConfigManager()
    config = config_mgr.load()

    if config.workers.enabled is None:
        config.workers.enabled = []

    if name not in config.workers.enabled:
        config.workers.enabled.append(name)

    if name in config.workers.disabled:
        config.workers.disabled.remove(name)

    config_mgr.save(config)
    console.print(f"[green]✓[/green] Worker '{name}' enabled")


@workers.command(name="disable")
def disable_worker(name: str) -> None:
    """禁用指定 Worker"""
    config_mgr = ConfigManager()
    config = config_mgr.load()

    if name not in config.workers.disabled:
        config.workers.disabled.append(name)

    if config.workers.enabled and name in config.workers.enabled:
        config.workers.enabled.remove(name)

    config_mgr.save(config)
    console.print(f"[yellow]✓[/yellow] Worker '{name}' disabled")
```

### 🧪 测试策略

```python
# tests/test_worker_registry.py

import pytest
from pathlib import Path
from src.workers.registry import WorkerRegistry
from src.workers.base import BaseWorker


def test_discover_builtin_workers():
    """发现内置 Workers"""
    registry = WorkerRegistry()
    registry.discover_builtin_workers()

    workers = registry.list_all()
    assert "system" in workers
    assert "container" in workers


def test_filter_enabled_workers():
    """只加载启用的 Workers"""
    registry = WorkerRegistry(enabled_workers=["system", "container"])
    registry.discover_builtin_workers()

    workers = registry.list_all()
    assert "system" in workers
    assert "container" in workers
    assert "kubernetes" not in workers  # 未启用


def test_register_custom_worker():
    """注册自定义 Worker"""
    class CustomWorker(BaseWorker):
        @property
        def name(self) -> str:
            return "custom"

        @property
        def description(self) -> str:
            return "Test"

        def get_capabilities(self) -> list[str]:
            return ["test"]

        def get_actions(self) -> list:
            return []

        async def execute(self, action: str, args: dict) -> WorkerResult:
            pass

    registry = WorkerRegistry()
    worker = CustomWorker()
    registry.register(worker)

    assert registry.get("custom") == worker


def test_plugin_discovery(tmp_path):
    """发现插件目录中的 Workers"""
    # 创建插件目录
    plugin_dir = tmp_path / "plugins" / "my_plugin"
    plugin_dir.mkdir(parents=True)

    # 创建插件代码
    plugin_code = '''
from src.workers.base import BaseWorker

class MyPluginWorker(BaseWorker):
    @property
    def name(self) -> str:
        return "myplugin"

    @property
    def description(self) -> str:
        return "Plugin worker"

    def get_capabilities(self) -> list[str]:
        return ["test"]

    def get_actions(self) -> list:
        return []

    async def execute(self, action: str, args: dict):
        pass
'''
    (plugin_dir / "__init__.py").write_text(plugin_code)

    registry = WorkerRegistry()
    registry.discover_plugin_workers(tmp_path / "plugins")

    assert "myplugin" in registry.list_all()
```

### 📈 成功指标

- 启动时间减少 30%（只加载启用的 Workers）
- 支持至少 3 个第三方插件示例
- Worker 启用/禁用无需重启

### 🔄 迁移路径

1. **Phase 1** (Week 2, Day 4-5): 实现 WorkerRegistry
2. **Phase 2** (Week 3, Day 1): 重构 Engine 使用 Registry
3. **Phase 3** (Week 3, Day 2): 添加 CLI 命令和配置
4. **Phase 4** (Week 3, Day 3): 插件示例和文档

---

## P0-4: Token 预算与成本控制

### 📊 当前问题

1. **无 Token 统计**: 不知道每次请求消耗多少 Token
2. **无预算控制**: 用户可能因费用过高而放弃使用
3. **ReAct 循环可能失控**: 最多 10 次迭代，但无 Token 上限
4. **无成本可见性**: 用户不知道当前花费

### 🎯 设计目标

- 实时 Token 统计（输入/输出分开）
- 每日/每月预算限制
- 达到阈值时告警
- 成本估算（基于模型定价）

### 📐 架构设计

```
┌──────────────────────────────────────┐
│      TokenBudgetManager              │
├──────────────────────────────────────┤
│  - track_usage()                     │
│  - check_budget()                    │
│  - get_stats()                       │
│  - reset_daily/monthly()             │
└──────────────────────────────────────┘
         │
         v
┌──────────────────────────────────────┐
│  ~/.opsai/token_usage.json           │
├──────────────────────────────────────┤
│  {                                   │
│    "daily": {"tokens": 12000, ...},  │
│    "monthly": {"tokens": 350000, ...}│
│  }                                   │
└──────────────────────────────────────┘
```

### 💻 代码实现

#### 1. Token 预算管理器

```python
# src/llm/token_budget.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional


@dataclass
class UsageStats:
    """使用统计"""

    tokens_input: int = 0
    tokens_output: int = 0
    requests: int = 0
    estimated_cost: float = 0.0  # USD
    date: str = ""

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output


class TokenBudgetManager:
    """Token 预算管理"""

    # 模型定价（每 1M tokens 价格，USD）
    MODEL_PRICING = {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "deepseek-chat": {"input": 0.27, "output": 1.1},
        "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
        "qwen2.5:7b": {"input": 0.0, "output": 0.0},  # 本地模型免费
    }

    def __init__(
        self,
        storage_path: Path,
        daily_limit: Optional[int] = None,
        monthly_limit: Optional[int] = None,
        model: str = "gpt-4o",
    ) -> None:
        """初始化预算管理器

        Args:
            storage_path: 存储路径
            daily_limit: 每日 Token 上限
            monthly_limit: 每月 Token 上限
            model: 模型名称（用于成本估算）
        """
        self.storage_path = storage_path
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.model = model

        self._data = self._load()

    def _load(self) -> dict:
        """加载使用数据"""
        if not self.storage_path.exists():
            return {"daily": {}, "monthly": {}}

        with open(self.storage_path) as f:
            return json.load(f)

    def _save(self) -> None:
        """保存使用数据"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(self._data, f, indent=2)

    def track_usage(
        self, tokens_input: int, tokens_output: int
    ) -> tuple[bool, Optional[str]]:
        """记录使用情况

        Returns:
            (是否允许继续, 警告消息)
        """
        today = date.today().isoformat()
        month = today[:7]  # YYYY-MM

        # 更新每日统计
        if today not in self._data["daily"]:
            self._data["daily"][today] = asdict(UsageStats(date=today))

        daily_stats = self._data["daily"][today]
        daily_stats["tokens_input"] += tokens_input
        daily_stats["tokens_output"] += tokens_output
        daily_stats["requests"] += 1
        daily_stats["estimated_cost"] += self._calculate_cost(
            tokens_input, tokens_output
        )

        # 更新每月统计
        if month not in self._data["monthly"]:
            self._data["monthly"][month] = asdict(UsageStats(date=month))

        monthly_stats = self._data["monthly"][month]
        monthly_stats["tokens_input"] += tokens_input
        monthly_stats["tokens_output"] += tokens_output
        monthly_stats["requests"] += 1
        monthly_stats["estimated_cost"] += self._calculate_cost(
            tokens_input, tokens_output
        )

        self._save()

        # 检查预算
        return self._check_limits(daily_stats, monthly_stats)

    def _calculate_cost(self, tokens_input: int, tokens_output: int) -> float:
        """计算成本"""
        pricing = self.MODEL_PRICING.get(self.model, {"input": 0, "output": 0})
        cost_input = (tokens_input / 1_000_000) * pricing["input"]
        cost_output = (tokens_output / 1_000_000) * pricing["output"]
        return cost_input + cost_output

    def _check_limits(
        self, daily_stats: dict, monthly_stats: dict
    ) -> tuple[bool, Optional[str]]:
        """检查是否超限"""
        daily_total = daily_stats["tokens_input"] + daily_stats["tokens_output"]
        monthly_total = monthly_stats["tokens_input"] + monthly_stats["tokens_output"]

        # 每日限制
        if self.daily_limit and daily_total >= self.daily_limit:
            return False, f"已达到每日 Token 上限 ({self.daily_limit:,})"

        # 每月限制
        if self.monthly_limit and monthly_total >= self.monthly_limit:
            return False, f"已达到每月 Token 上限 ({self.monthly_limit:,})"

        # 警告阈值（80%）
        warning = None
        if self.daily_limit and daily_total > self.daily_limit * 0.8:
            pct = (daily_total / self.daily_limit) * 100
            warning = f"⚠️  今日已使用 {pct:.0f}% Token 配额"

        if self.monthly_limit and monthly_total > self.monthly_limit * 0.8:
            pct = (monthly_total / self.monthly_limit) * 100
            warning = f"⚠️  本月已使用 {pct:.0f}% Token 配额"

        return True, warning

    def get_today_stats(self) -> UsageStats:
        """获取今日统计"""
        today = date.today().isoformat()
        data = self._data["daily"].get(today, asdict(UsageStats(date=today)))
        return UsageStats(**data)

    def get_month_stats(self) -> UsageStats:
        """获取本月统计"""
        month = date.today().isoformat()[:7]
        data = self._data["monthly"].get(month, asdict(UsageStats(date=month)))
        return UsageStats(**data)

    def reset_daily(self) -> None:
        """重置每日统计（自动在日期变更时调用）"""
        today = date.today().isoformat()
        # 只保留最近 30 天
        cutoff = (datetime.now() - timedelta(days=30)).date().isoformat()
        self._data["daily"] = {
            d: stats
            for d, stats in self._data["daily"].items()
            if d >= cutoff
        }
        self._save()
```

#### 2. 集成到 LLMClient

```python
# src/llm/client.py (修改)

from src.llm.token_budget import TokenBudgetManager

class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        # ... 现有代码 ...

        # Token 预算管理
        budget_path = Path.home() / ".opsai" / "token_usage.json"
        self._budget_manager = TokenBudgetManager(
            storage_path=budget_path,
            daily_limit=config.daily_token_limit,
            monthly_limit=config.monthly_token_limit,
            model=config.model,
        )

    async def chat(
        self, messages: list[dict[str, str]], tools: Optional[list] = None
    ) -> ChatResponse:
        """发送聊天请求（增加 Token 追踪）"""
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=messages,
                tools=tools,
                # ... 其他参数 ...
            )

            # 记录 Token 使用
            usage = response.usage
            if usage:
                allowed, warning = self._budget_manager.track_usage(
                    tokens_input=usage.prompt_tokens,
                    tokens_output=usage.completion_tokens,
                )

                if warning:
                    # 发出警告（通过 logging 或回调）
                    print(warning)

                if not allowed:
                    raise RuntimeError("Token 预算已耗尽，请检查配置")

            # ... 原有返回逻辑 ...

        except Exception as e:
            # ... 错误处理 ...
```

#### 3. 配置支持

```python
# src/config/manager.py (修改)

class LLMConfig(BaseModel):
    # ... 现有字段 ...
    daily_token_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = 1_000_000  # 默认 100 万/月
```

#### 4. CLI 命令

```python
# src/cli.py (新增)

@app.command()
def usage() -> None:
    """查看 Token 使用情况"""
    from rich.table import Table

    budget_path = Path.home() / ".opsai" / "token_usage.json"
    config = ConfigManager().load()
    manager = TokenBudgetManager(
        storage_path=budget_path,
        daily_limit=config.llm.daily_token_limit,
        monthly_limit=config.llm.monthly_token_limit,
        model=config.llm.model,
    )

    today = manager.get_today_stats()
    month = manager.get_month_stats()

    table = Table(title="Token Usage")
    table.add_column("Period", style="cyan")
    table.add_column("Tokens (In)", style="green", justify="right")
    table.add_column("Tokens (Out)", style="yellow", justify="right")
    table.add_column("Total", style="magenta", justify="right")
    table.add_column("Requests", justify="right")
    table.add_column("Est. Cost", style="red", justify="right")

    table.add_row(
        "Today",
        f"{today.tokens_input:,}",
        f"{today.tokens_output:,}",
        f"{today.tokens_total:,}",
        str(today.requests),
        f"${today.estimated_cost:.4f}",
    )

    table.add_row(
        "This Month",
        f"{month.tokens_input:,}",
        f"{month.tokens_output:,}",
        f"{month.tokens_total:,}",
        str(month.requests),
        f"${month.estimated_cost:.2f}",
    )

    console.print(table)

    # 显示限制
    if config.llm.daily_token_limit:
        pct = (today.tokens_total / config.llm.daily_token_limit) * 100
        console.print(f"\n📊 Daily limit: {pct:.1f}% used")

    if config.llm.monthly_token_limit:
        pct = (month.tokens_total / config.llm.monthly_token_limit) * 100
        console.print(f"📊 Monthly limit: {pct:.1f}% used")
```

### 🧪 测试策略

```python
# tests/test_token_budget.py

import pytest
from pathlib import Path
from src.llm.token_budget import TokenBudgetManager, UsageStats


def test_track_usage(tmp_path):
    """记录 Token 使用"""
    manager = TokenBudgetManager(
        storage_path=tmp_path / "usage.json",
        daily_limit=10000,
    )

    allowed, warning = manager.track_usage(1000, 500)
    assert allowed is True
    assert warning is None

    stats = manager.get_today_stats()
    assert stats.tokens_input == 1000
    assert stats.tokens_output == 500
    assert stats.tokens_total == 1500


def test_daily_limit_exceeded(tmp_path):
    """超过每日限制"""
    manager = TokenBudgetManager(
        storage_path=tmp_path / "usage.json",
        daily_limit=1000,
    )

    # 第一次：允许
    allowed, _ = manager.track_usage(800, 0)
    assert allowed is True

    # 第二次：超限
    allowed, msg = manager.track_usage(300, 0)
    assert allowed is False
    assert "每日 Token 上限" in msg


def test_warning_threshold(tmp_path):
    """达到 80% 阈值时警告"""
    manager = TokenBudgetManager(
        storage_path=tmp_path / "usage.json",
        daily_limit=1000,
    )

    allowed, warning = manager.track_usage(850, 0)
    assert allowed is True
    assert warning is not None
    assert "已使用" in warning


def test_cost_calculation(tmp_path):
    """成本计算"""
    manager = TokenBudgetManager(
        storage_path=tmp_path / "usage.json",
        model="gpt-4o",
    )

    manager.track_usage(1_000_000, 1_000_000)
    stats = manager.get_today_stats()

    # gpt-4o: $2.5/M input + $10/M output = $12.5 for 2M tokens
    assert abs(stats.estimated_cost - 12.5) < 0.01
```

### 📈 成功指标

- Token 统计准确率 100%
- 成本估算误差 < 5%
- 预算超限前 100% 阻止请求

### 🔄 迁移路径

1. **Phase 1** (Week 2, Day 6): 实现 TokenBudgetManager
2. **Phase 2** (Week 2, Day 7): 集成到 LLMClient
3. **Phase 3** (Week 3, Day 4): 添加 CLI 和配置
4. **Phase 4** (Week 3, Day 5): 文档和示例

---

## P1-1: ErrorHelper 智能错误提示

*(继续在文档中补充 P1-1 到 P1-3 的详细内容...)*

### 📊 当前问题

1. **错误消息不友好**: 只显示失败原因，不提供解决方案
2. **用户陷入困境**: 不知道下一步该做什么
3. **重复错误**: 用户可能多次尝试相同的错误操作

### 🎯 设计目标

- 根据错误类型提供 2-3 个可操作建议
- 建议基于上下文（如：检测到的环境）
- 支持"一键重试"推荐命令

### 💻 代码实现

```python
# src/orchestrator/error_helper.py
from __future__ import annotations

import re
from typing import Optional

from src.types import WorkerResult


class ErrorHelper:
    """智能错误提示生成器"""

    ERROR_PATTERNS = [
        # 容器相关
        {
            "pattern": r"Container '(\w+)' not found",
            "suggestions": [
                "💡 查看所有容器: 列出所有容器",
                "💡 检查容器名拼写",
                "💡 容器可能已停止: docker ps -a",
            ],
        },
        # 权限相关
        {
            "pattern": r"Permission denied",
            "suggestions": [
                "💡 检查文件权限: ls -l <文件>",
                "💡 可能需要 sudo 权限",
                "💡 检查当前用户: whoami",
            ],
        },
        # 网络相关
        {
            "pattern": r"(Connection refused|Connection timed out)",
            "suggestions": [
                "💡 检查服务是否启动",
                "💡 检查防火墙规则",
                "💡 确认端口号正确",
            ],
        },
        # 磁盘相关
        {
            "pattern": r"No space left on device",
            "suggestions": [
                "💡 清理磁盘空间: 查找大文件",
                "💡 检查磁盘使用: 查看磁盘使用情况",
                "💡 清理 Docker 镜像: docker system prune",
            ],
        },
    ]

    def suggest_fixes(self, error: WorkerResult) -> list[str]:
        """生成修复建议

        Args:
            error: 失败的 WorkerResult

        Returns:
            建议列表
        """
        message = error.message or ""

        # 匹配错误模式
        for pattern_config in self.ERROR_PATTERNS:
            if re.search(pattern_config["pattern"], message):
                return pattern_config["suggestions"]

        # 默认建议
        return [
            "💡 查看详细错误信息",
            "💡 检查命令语法",
            "💡 尝试 /help 获取帮助",
        ]

    def format_error_with_suggestions(self, error: WorkerResult) -> str:
        """格式化错误消息（包含建议）"""
        suggestions = self.suggest_fixes(error)
        lines = [
            f"❌ {error.message}",
            "",
            "建议:",
        ]
        lines.extend(suggestions)
        return "\n".join(lines)
```

#### 集成到 TUI

```python
# src/tui/app.py (修改)

from src.orchestrator.error_helper import ErrorHelper

class OpsAIApp(App):
    def __init__(self):
        # ... 现有代码 ...
        self._error_helper = ErrorHelper()

    async def _handle_worker_error(self, result: WorkerResult) -> None:
        """处理 Worker 错误"""
        # 显示错误和建议
        formatted = self._error_helper.format_error_with_suggestions(result)
        self._append_message("assistant", formatted)

        # 提供快捷重试按钮
        suggestions = self._error_helper.suggest_fixes(result)
        if suggestions:
            # 提取可执行的命令（如果有）
            commands = self._extract_commands_from_suggestions(suggestions)
            if commands:
                self._show_retry_buttons(commands)
```

### 🧪 测试策略

```python
# tests/test_error_helper.py

from src.orchestrator.error_helper import ErrorHelper
from src.types import WorkerResult


def test_container_not_found_suggestions():
    """容器未找到时的建议"""
    helper = ErrorHelper()
    error = WorkerResult(
        success=False,
        message="Container 'nginx' not found",
    )

    suggestions = helper.suggest_fixes(error)
    assert len(suggestions) > 0
    assert any("列出所有容器" in s for s in suggestions)


def test_permission_denied_suggestions():
    """权限错误建议"""
    helper = ErrorHelper()
    error = WorkerResult(
        success=False,
        message="Permission denied: /var/log/system.log",
    )

    suggestions = helper.suggest_fixes(error)
    assert any("权限" in s for s in suggestions)
```

---

## 总结与下一步

### 📅 实施时间表

| 阶段 | 任务 | 工期 | 负责人 |
|------|------|------|--------|
| Week 1 | P0-1 首次运行引导 | 2 天 | TBD |
| Week 1 | P0-2 命令缓存 (Phase 1-2) | 3 天 | TBD |
| Week 2 | P0-2 命令缓存 (Phase 3-4) | 2 天 | TBD |
| Week 2 | P0-3 Worker 插件化 (Phase 1-2) | 3 天 | TBD |
| Week 2 | P0-4 Token 预算 | 2 天 | TBD |
| Week 3 | P0-3 Worker 插件化 (Phase 3-4) | 2 天 | TBD |
| Week 3 | P0-4 Token 预算完善 | 2 天 | TBD |
| Week 3 | P1-1, P1-2, P1-3 | 3 天 | TBD |

### 🎯 v0.4.0 Release Checklist

- [ ] 所有 P0 功能实现并测试
- [ ] 测试覆盖率 > 60%
- [ ] 文档更新（README + 新功能说明）
- [ ] 迁移指南
- [ ] 性能基准测试
- [ ] 至少 3 个真实用户试用反馈

### 📊 预期改进

| 指标 | 当前 | 目标 (v0.4.0) |
|------|------|----------------|
| 首次成功率 | ~50% | 80%+ |
| 平均响应时间 | 3-5s | < 2s (70%请求) |
| Token 使用量 | 基线 | -40% |
| 用户放弃率 | ~40% | < 20% |
| 缓存命中率 | 0% | 60%+ |

---

**文档版本**: 1.0  
**最后更新**: 2026-02-26  
**作者**: OpsAI Team
