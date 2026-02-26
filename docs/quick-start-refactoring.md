# OpsAI 重构快速开始指南

> 🚀 从零到一，30分钟完成第一个重构模块

---

## 📋 准备工作清单

### 开发环境

```bash
# 1. 确认环境
python3 --version  # >= 3.9
git --version

# 2. 进入项目
cd /Users/zhangyanhua/AI/mainer-cli

# 3. 安装依赖
uv sync

# 4. 运行测试确保基线稳定
uv run pytest
# 预期: 所有测试通过

# 5. 创建重构分支
git checkout -b feature/v0.4.0-refactoring
```

### 阅读材料

- [ ] [refactoring-plan.md](./refactoring-plan.md) - 详细重构方案
- [ ] [architecture-evolution.md](./architecture-evolution.md) - 架构演进对比
- [ ] [CLAUDE.md](../CLAUDE.md) - 项目编码规范

---

## 🎯 模块实施顺序

### Week 1: 快速见效模块

#### Day 1-2: P0-1 首次运行引导 (难度: ⭐⭐)

**为什么先做这个？**
- ✅ 独立模块，不影响现有代码
- ✅ 用户体验立即改善
- ✅ 测试简单，风险低

**实施步骤**:

```bash
# Step 1: 创建目录结构
mkdir -p src/tui/widgets
touch src/tui/widgets/first_run_wizard.py

# Step 2: 实现 FirstRunWizard Widget
# (参考 refactoring-plan.md P0-1 章节)

# Step 3: 集成到 TUI App
# 修改 src/tui/app.py

# Step 4: 测试
uv run pytest tests/test_first_run_wizard.py -v

# Step 5: 手动测试
rm ~/.opsai/first_run  # 清除标记
uv run opsai-tui       # 应该看到引导页面
```

**验收标准**:
- [ ] 首次启动自动显示引导
- [ ] 点击推荐命令可执行
- [ ] 跳过后不再显示
- [ ] 测试覆盖率 > 80%

---

#### Day 3-4: P0-2 命令缓存 Phase 1 (难度: ⭐⭐⭐)

**核心价值**: 响应速度提升 3x

**实施步骤**:

```bash
# Step 1: 创建 CommandCache 模块
touch src/orchestrator/command_cache.py

# Step 2: 实现核心逻辑
# (参考 refactoring-plan.md P0-2 章节)

# Step 3: 添加 20+ 高频模式
# 参考日志分析最常用命令

# Step 4: 单元测试
uv run pytest tests/test_command_cache.py -v

# Step 5: 集成到 Engine (可选开关)
# 修改 src/orchestrator/engine.py
# 修改 src/config/manager.py (添加 PerformanceConfig)
```

**验收标准**:
- [ ] 至少 20 个命令模式
- [ ] 匹配准确率 > 95%
- [ ] 参数提取正确
- [ ] 测试覆盖率 > 90%

---

#### Day 5: P0-2 命令缓存 Phase 2 (难度: ⭐⭐)

**集成测试**:

```bash
# Step 1: 集成测试
uv run pytest tests/test_engine.py::test_command_cache_integration -v

# Step 2: 性能测试
uv run python tests/perf/benchmark_cache.py

# 预期结果:
# - 缓存命中: < 100ms
# - LLM fallback: 2-3s

# Step 3: 添加统计信息
# Engine 暴露 get_cache_stats() 方法

# Step 4: TUI 显示缓存命中率
# 在 /config 命令中显示
```

**验收标准**:
- [ ] 缓存命中响应 < 500ms
- [ ] LLM Fallback 正常工作
- [ ] 统计信息准确

---

### Week 2: 架构升级

#### Day 1-3: P0-3 Worker 插件化 Phase 1-2 (难度: ⭐⭐⭐⭐)

**关键挑战**: 重构现有代码，保持兼容性

**实施步骤**:

```bash
# Step 1: 创建 WorkerRegistry
touch src/workers/registry.py

# Step 2: 实现发现与注册逻辑
# (参考 refactoring-plan.md P0-3 章节)

# Step 3: 重构 Engine 使用 Registry
# ⚠️ 保持向后兼容！

# Step 4: 测试所有 Workers 仍正常工作
uv run pytest tests/test_worker_registry.py -v
uv run pytest tests/test_integration.py -v

# Step 5: 创建插件示例
mkdir -p ~/.opsai/plugins/example_worker
# 实现一个简单的 HelloWorker
```

**验收标准**:
- [ ] 所有现有测试通过
- [ ] 支持配置启用/禁用
- [ ] 插件自动发现
- [ ] 至少 1 个插件示例

---

#### Day 4-5: P0-4 Token 预算管理 (难度: ⭐⭐⭐)

**核心价值**: 成本可控

**实施步骤**:

```bash
# Step 1: 创建 TokenBudgetManager
touch src/llm/token_budget.py

# Step 2: 实现追踪和限制逻辑
# (参考 refactoring-plan.md P0-4 章节)

# Step 3: 集成到 LLMClient
# 修改 src/llm/client.py

# Step 4: 添加 CLI 命令
# opsai usage

# Step 5: 测试预算超限阻止
uv run pytest tests/test_token_budget.py -v
```

**验收标准**:
- [ ] Token 统计准确
- [ ] 成本估算误差 < 5%
- [ ] 超限时阻止请求
- [ ] CLI 可查看使用情况

---

### Week 3: 体验优化

#### Day 1-2: P0-3 Worker 插件化 Phase 3-4 (难度: ⭐⭐)

**CLI 命令和文档**:

```bash
# Step 1: 实现 opsai workers 命令
# - list: 列出所有 Workers
# - enable <name>: 启用 Worker
# - disable <name>: 禁用 Worker

# Step 2: 文档
# 创建 docs/plugins-guide.md

# Step 3: 插件模板
# 创建 ~/.opsai/plugin-template/

# Step 4: 示例插件
# 至少 3 个：HelloWorker, SlackWorker, CustomMonitorWorker
```

---

#### Day 3: P1-1 ErrorHelper (难度: ⭐⭐)

**快速实施**:

```bash
# Step 1: 创建 ErrorHelper
touch src/orchestrator/error_helper.py

# Step 2: 实现错误模式匹配
# (参考 refactoring-plan.md P1-1 章节)

# Step 3: 集成到 TUI
# 修改 src/tui/app.py

# Step 4: 测试
uv run pytest tests/test_error_helper.py -v
```

---

#### Day 4-5: 测试、文档、发布

```bash
# Step 1: 完整测试
uv run pytest --cov=src --cov-report=term-missing

# Step 2: 性能基准测试
uv run python tests/perf/benchmark_suite.py

# Step 3: 更新文档
# - README.md
# - CHANGELOG.md
# - docs/NEW_FEATURES.md

# Step 4: 用户试用
# 邀请 5-10 个真实用户测试

# Step 5: 发布 v0.4.0
git tag v0.4.0
git push origin v0.4.0
```

---

## 🧪 测试策略

### 单元测试模板

```python
# tests/test_command_cache.py
import pytest
from src.orchestrator.command_cache import CommandCache


class TestCommandCache:
    """CommandCache 单元测试"""

    def test_exact_match(self):
        """精确匹配测试"""
        cache = CommandCache()
        result = cache.match("查看容器")

        assert result is not None
        instruction, confidence = result
        assert instruction.worker == "container"
        assert instruction.action == "list"
        assert confidence > 0.8

    def test_regex_with_args(self):
        """正则匹配 + 参数提取"""
        cache = CommandCache()
        result = cache.match("重启 nginx")

        assert result is not None
        instruction, _ = result
        assert instruction.args["container_id"] == "nginx"

    @pytest.mark.parametrize("input_text", [
        "查看容器",
        "列出容器",
        "显示所有容器",
    ])
    def test_multiple_patterns(self, input_text):
        """多种表达方式测试"""
        cache = CommandCache()
        result = cache.match(input_text)
        assert result is not None
```

### 集成测试模板

```python
# tests/test_integration.py
@pytest.mark.asyncio
async def test_cache_integration():
    """缓存与 Engine 集成测试"""
    config = ConfigManager().load()
    engine = OrchestratorEngine(config)

    # 第一次：缓存命中
    start = time.time()
    result = await engine.process("查看容器")
    duration = time.time() - start

    assert result.success
    assert duration < 1.0  # 应该很快

    # 验证统计
    stats = engine.get_cache_stats()
    assert stats["container.list"] == 1
```

### 性能基准测试

```python
# tests/perf/benchmark_cache.py
import time
from src.orchestrator.command_cache import CommandCache


def benchmark_cache_performance():
    """性能基准测试"""
    cache = CommandCache()
    test_cases = [
        "查看容器",
        "重启 nginx",
        "检查磁盘空间",
        # ... 100 个测试用例
    ]

    start = time.time()
    for text in test_cases * 100:  # 10,000 次匹配
        cache.match(text)
    duration = time.time() - start

    print(f"10,000 次匹配耗时: {duration:.2f}s")
    print(f"平均每次: {duration / 10000 * 1000:.2f}ms")

    # 预期: < 1ms/次


if __name__ == "__main__":
    benchmark_cache_performance()
```

---

## 🐛 常见问题

### Q1: 缓存模式匹配不准确怎么办？

**A**: 降低置信度阈值，让更多请求 Fallback 到 LLM

```python
# src/config/manager.py
class PerformanceConfig(BaseModel):
    cache_confidence_threshold: float = 0.75  # 降低到 0.75
```

### Q2: Worker 注册失败怎么排查？

**A**: 检查依赖和日志

```python
# src/workers/registry.py
def _load_worker_module(self, module_path: str) -> None:
    try:
        module = importlib.import_module(module_path)
        # ...
    except ImportError as e:
        logger.warning(f"Failed to load worker {module_path}: {e}")
        # 继续加载其他 Workers
```

### Q3: Token 统计不准确？

**A**: 使用 LLM API 返回的真实 usage

```python
# src/llm/client.py
response = await self._client.chat.completions.create(...)
if response.usage:
    # 使用 API 返回的真实值
    self._budget_manager.track_usage(
        tokens_input=response.usage.prompt_tokens,
        tokens_output=response.usage.completion_tokens,
    )
```

### Q4: 首次引导弹出过于频繁？

**A**: 检查标记文件逻辑

```python
# src/tui/widgets/first_run_wizard.py
@staticmethod
def should_show() -> bool:
    marker = Path.home() / ".opsai" / "first_run"
    return not marker.exists()  # 只有不存在时才显示

@staticmethod
def _mark_completed() -> None:
    marker = Path.home() / ".opsai" / "first_run"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()  # 创建空文件
```

---

## 📊 进度追踪

### 每日检查清单

```markdown
## Week 1
- [ ] Day 1: FirstRunWizard 实现
- [ ] Day 2: FirstRunWizard 测试和集成
- [ ] Day 3: CommandCache 核心逻辑
- [ ] Day 4: CommandCache 模式库
- [ ] Day 5: CommandCache 集成测试

## Week 2
- [ ] Day 1: WorkerRegistry 实现
- [ ] Day 2: Engine 重构
- [ ] Day 3: 插件示例
- [ ] Day 4: TokenBudgetManager 实现
- [ ] Day 5: Token 追踪集成

## Week 3
- [ ] Day 1: Worker CLI 命令
- [ ] Day 2: 插件文档
- [ ] Day 3: ErrorHelper
- [ ] Day 4: 完整测试
- [ ] Day 5: 文档和发布
```

### 提交规范

```bash
# 功能实现
git commit -m "feat(orchestrator): add CommandCache for fast pattern matching"

# 测试
git commit -m "test(orchestrator): add CommandCache unit tests"

# 文档
git commit -m "docs: add quick-start refactoring guide"

# 重构
git commit -m "refactor(engine): use WorkerRegistry for dynamic worker loading"

# 修复
git commit -m "fix(cache): improve regex pattern matching accuracy"
```

---

## 🎯 成功指标

### 每周目标

**Week 1**:
- ✅ 首次引导实现并测试
- ✅ 缓存命中率 > 60%
- ✅ 响应时间 < 1s (缓存命中)

**Week 2**:
- ✅ Worker 插件化完成
- ✅ Token 追踪准确
- ✅ 所有原有测试通过

**Week 3**:
- ✅ 至少 3 个插件示例
- ✅ 文档完整
- ✅ 用户试用反馈 > 4/5

---

## 🚀 快速验证

### 1 分钟快速测试

```bash
# 测试缓存
time uv run opsai query "查看容器"
# 预期: < 1s

# 测试 Token 统计
uv run opsai usage
# 预期: 显示今日和本月使用情况

# 测试 Worker 列表
uv run opsai workers list
# 预期: 显示所有可用 Workers

# 测试首次引导
rm ~/.opsai/first_run
uv run opsai-tui
# 预期: 显示引导页面
```

---

## 📚 参考资源

- **详细设计**: [refactoring-plan.md](./refactoring-plan.md)
- **架构对比**: [architecture-evolution.md](./architecture-evolution.md)
- **编码规范**: [CLAUDE.md](../CLAUDE.md)
- **现有文档**: [README.md](../README.md)

---

## 💬 获取帮助

遇到问题？

1. 检查 [常见问题](#🐛-常见问题)
2. 查看详细设计文档
3. 运行测试验证问题
4. 提交 Issue (包含错误日志)

---

**下一步**: 选择一个模块开始吧！推荐从 **P0-1 首次运行引导** 开始。
