# OpsAI 优化实施详细计划

> 基于产品优化建议报告的可执行实施计划
> 预计总工期：6-8 周
> 团队规模：1-2 人

---

## 📅 项目时间线总览

```
Week 1-2:  P0 阶段 - 核心功能精简
Week 3-4:  P1 阶段 - 体验优化（第一部分）
Week 5-6:  P1 阶段 - 体验优化（第二部分）
Week 7-8:  P2 阶段 - 功能增强（可选）
```

---

## 🎯 P0 阶段：核心功能精简（第 1-2 周）

**目标**：删减 30% 的代码，让核心场景体验提升 300%

### Task 1.1：移除 Tavily 搜索依赖 ⏱️ 4 小时

**为什么做**：
- 外部搜索在运维场景价值有限
- 减少 API 配置成本
- 降低 LLM 生成不确定性

**具体步骤**：

#### 1.1.1 代码移除
```bash
# 1. 删除 Worker 文件
rm src/workers/tavily.py

# 2. 删除测试文件
rm tests/test_tavily_worker.py

# 3. 更新 pyproject.toml
# 删除依赖：tavily-python>=0.5.0
```

#### 1.1.2 清理引用
```python
# 文件：src/orchestrator/prompt.py
# 删除 WORKER_CAPABILITIES 中的 tavily 配置
WORKER_CAPABILITIES: dict[str, list[str]] = {
    # ...
    # "tavily": ["search", "extract"],  # ← 删除这行
}
```

```python
# 文件：src/orchestrator/engine.py
# 删除 TavilyWorker 的导入和注册
# from src.workers.tavily import TavilyWorker  # ← 删除
# self._workers["tavily"] = TavilyWorker(...)  # ← 删除
```

#### 1.1.3 验证
```bash
# 运行测试确保没有残留引用
uv run pytest -v
uv run mypy src/
```

**产出**：
- ✅ 删除 2 个文件（~400 行代码）
- ✅ 减少 1 个外部依赖
- ✅ 通过所有测试

---

### Task 1.2：合并 cache.py 到 analyze.py ⏱️ 6 小时

**为什么做**：
- Cache 是 Analyze 的内部实现细节，不应独立暴露
- 简化 Workers 数量，降低理解成本

**具体步骤**：

#### 1.2.1 重构 AnalyzeWorker
```python
# 文件：src/workers/analyze.py

from typing import Optional
import json
from pathlib import Path

class AnalyzeWorker(BaseWorker):
    """智能分析 Worker（内置缓存）"""
    
    # 内部缓存管理
    _CACHE_FILE = Path.home() / ".opsai" / "analyze_cache.json"
    
    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client
        self._shell_worker = ShellWorker()
        self._cache: dict[str, list[str]] = self._load_cache()
    
    def _load_cache(self) -> dict[str, list[str]]:
        """加载缓存（内部方法）"""
        if self._CACHE_FILE.exists():
            try:
                with open(self._CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _save_cache(self) -> None:
        """保存缓存（内部方法）"""
        self._CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._CACHE_FILE, "w") as f:
            json.dump(self._cache, f, indent=2)
    
    def _get_cached_commands(self, target_type: str) -> Optional[list[str]]:
        """从缓存获取命令"""
        return self._cache.get(target_type)
    
    def _cache_commands(self, target_type: str, commands: list[str]) -> None:
        """缓存命令"""
        self._cache[target_type] = commands
        self._save_cache()
    
    async def _get_analyze_commands(self, target_type: str, target_name: str) -> list[str]:
        """获取分析命令列表（优先级：缓存 > 预置 > LLM）"""
        # 1. 尝试从缓存获取
        cached = self._get_cached_commands(target_type)
        if cached:
            return cached
        
        # 2. 使用预置默认命令
        if target_type in DEFAULT_ANALYZE_COMMANDS:
            return DEFAULT_ANALYZE_COMMANDS[target_type]
        
        # 3. LLM 生成
        commands = await self._generate_commands_via_llm(target_type, target_name)
        if commands:
            self._cache_commands(target_type, commands)
        
        return commands
```

#### 1.2.2 删除旧文件
```bash
# 删除独立的 Cache Worker
rm src/workers/cache.py
```

#### 1.2.3 更新测试
```python
# 文件：tests/test_analyze_worker.py

def test_analyze_with_internal_cache():
    """测试内置缓存功能"""
    worker = AnalyzeWorker(llm_client=mock_llm)
    
    # 第一次调用（生成并缓存）
    result1 = await worker.execute("explain", {"target": "nginx", "type": "docker"})
    
    # 第二次调用（从缓存读取）
    result2 = await worker.execute("explain", {"target": "nginx", "type": "docker"})
    
    # 验证缓存生效（LLM 只调用一次）
    assert mock_llm.call_count == 1
```

**产出**：
- ✅ 删除 1 个独立 Worker 文件（~150 行代码）
- ✅ AnalyzeWorker 代码增加 ~100 行（净减少 50 行）
- ✅ 更新相关测试

---

### Task 1.3：简化 Deploy 为一键部署 ⏱️ 8 小时

**为什么做**：
- 当前流程需要用户理解 4 个步骤（analyze → clone → setup → start）
- 新手只需要："给我一个 URL，直接启动"

**具体步骤**：

#### 1.3.1 新增高层接口
```python
# 文件：src/workers/deploy.py

class DeployWorker(BaseWorker):
    """GitHub 项目部署 Worker"""
    
    def get_capabilities(self) -> list[str]:
        # 简化对外能力：只暴露一键部署
        return ["deploy"]  # 不再暴露 analyze_repo, clone_repo 等
    
    async def execute(self, action: str, args: dict[str, ArgValue]) -> WorkerResult:
        if action == "deploy":
            return await self._one_click_deploy(args)
        # 保留内部方法（analyze, clone, setup, start）
        # 但不对外暴露
    
    async def _one_click_deploy(self, args: dict[str, ArgValue]) -> WorkerResult:
        """一键部署 GitHub 项目
        
        Args:
            args: {
                "repo_url": "https://github.com/owner/repo",
                "target_dir": "~/projects"  # 可选
            }
        
        Returns:
            WorkerResult: 部署结果（包含所有步骤的摘要）
        """
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required",
            )
        
        target_dir = args.get("target_dir", "~/projects")
        dry_run = args.get("dry_run", False)
        
        steps_log = []
        
        # Step 1: 分析项目
        steps_log.append("📋 Step 1/4: 分析项目结构...")
        analyze_result = await self._analyze_repo({"repo_url": repo_url})
        if not analyze_result.success:
            return WorkerResult(
                success=False,
                message=f"❌ 分析失败：{analyze_result.message}",
            )
        
        project_type = analyze_result.data.get("project_type", "unknown") if analyze_result.data else "unknown"
        steps_log.append(f"  ✓ 检测到项目类型：{project_type}")
        
        # Step 2: 克隆仓库
        steps_log.append("📦 Step 2/4: 克隆仓库...")
        clone_result = await self._clone_repo({
            "repo_url": repo_url,
            "target_dir": target_dir,
            "dry_run": dry_run,
        })
        if not clone_result.success:
            return WorkerResult(
                success=False,
                message="\n".join(steps_log) + f"\n❌ 克隆失败：{clone_result.message}",
            )
        
        project_dir = clone_result.data.get("path") if clone_result.data else ""
        already_exists = clone_result.data.get("already_exists", False) if clone_result.data else False
        if already_exists:
            steps_log.append(f"  ⚠️ 项目已存在：{project_dir}")
        else:
            steps_log.append(f"  ✓ 克隆完成：{project_dir}")
        
        # Step 3: 配置环境
        steps_log.append("⚙️  Step 3/4: 配置环境...")
        setup_result = await self._setup_env({
            "project_dir": project_dir,
            "project_type": project_type,
            "dry_run": dry_run,
        })
        if not setup_result.success:
            return WorkerResult(
                success=False,
                message="\n".join(steps_log) + f"\n❌ 环境配置失败：{setup_result.message}",
            )
        steps_log.append(f"  ✓ 环境配置完成")
        
        # Step 4: 启动服务
        steps_log.append("🚀 Step 4/4: 启动服务...")
        start_result = await self._start_service({
            "project_dir": project_dir,
            "project_type": project_type,
            "dry_run": dry_run,
        })
        if not start_result.success:
            # 启动失败时，提供详细的错误提示
            error_msg = start_result.message
            suggestions = self._generate_error_suggestions(project_type, error_msg)
            return WorkerResult(
                success=False,
                message="\n".join(steps_log) + 
                        f"\n❌ 启动失败：{error_msg}\n\n" +
                        f"💡 可能的解决方法：\n{suggestions}",
            )
        
        steps_log.append(f"  ✓ 服务启动成功！")
        
        # 成功摘要
        summary = "\n".join(steps_log)
        summary += f"\n\n✅ 部署完成！"
        summary += f"\n📂 项目路径：{project_dir}"
        summary += f"\n🎯 项目类型：{project_type}"
        
        if dry_run:
            summary = "[DRY-RUN 模式]\n\n" + summary
        
        return WorkerResult(
            success=True,
            data={
                "project_dir": str(project_dir),
                "project_type": str(project_type),
                "repo_url": repo_url,
            },
            message=summary,
            task_completed=True,
            simulated=dry_run,
        )
    
    def _generate_error_suggestions(self, project_type: str, error_msg: str) -> str:
        """根据错误信息生成建议"""
        suggestions = []
        
        if "permission denied" in error_msg.lower():
            suggestions.append("1. 检查文件权限：chmod +x start.sh")
            suggestions.append("2. 使用 sudo（如果需要）")
        
        if "port" in error_msg.lower() or "address already in use" in error_msg.lower():
            suggestions.append("1. 检查端口占用：lsof -i :端口号")
            suggestions.append("2. 修改配置文件中的端口")
        
        if ".env" in error_msg.lower() or "environment" in error_msg.lower():
            suggestions.append("1. 检查 .env 文件是否存在")
            suggestions.append("2. 从 .env.example 复制并填写必要配置")
        
        if project_type == "docker" and "docker" in error_msg.lower():
            suggestions.append("1. 确保 Docker 正在运行：docker ps")
            suggestions.append("2. 检查 docker-compose.yml 配置")
        
        if not suggestions:
            suggestions.append("1. 查看项目 README 了解部署要求")
            suggestions.append("2. 检查项目目录中的错误日志")
        
        return "\n".join(suggestions)
```

#### 1.3.2 更新 CLI 命令
```python
# 文件：src/cli.py

@app.command()
def deploy(
    repo_url: str = typer.Argument(..., help="GitHub 仓库 URL"),
    target_dir: str = typer.Option("~/projects", help="部署目标目录"),
    dry_run: bool = typer.Option(False, "--dry-run", help="模拟执行，不实际部署"),
):
    """一键部署 GitHub 项目
    
    示例：
        opsai deploy https://github.com/user/my-app
        opsai deploy https://github.com/user/my-app --target-dir ~/myprojects
        opsai deploy https://github.com/user/my-app --dry-run
    """
    console = Console()
    
    with console.status("[bold green]正在部署项目..."):
        # 调用 DeployWorker 的一键部署
        result = asyncio.run(_deploy_project(repo_url, target_dir, dry_run))
    
    if result.success:
        console.print(Panel(result.message, title="✅ 部署成功", border_style="green"))
    else:
        console.print(Panel(result.message, title="❌ 部署失败", border_style="red"))
        raise typer.Exit(code=1)

async def _deploy_project(repo_url: str, target_dir: str, dry_run: bool) -> WorkerResult:
    """执行部署"""
    from src.workers.deploy import DeployWorker
    from src.workers.http import HttpWorker
    from src.workers.shell import ShellWorker
    
    http_worker = HttpWorker()
    shell_worker = ShellWorker()
    deploy_worker = DeployWorker(http_worker, shell_worker)
    
    return await deploy_worker.execute("deploy", {
        "repo_url": repo_url,
        "target_dir": target_dir,
        "dry_run": dry_run,
    })
```

#### 1.3.3 更新 Prompt
```python
# 文件：src/orchestrator/prompt.py

WORKER_CAPABILITIES: dict[str, list[str]] = {
    # ...
    "deploy": ["deploy"],  # 简化：只显示一个能力
}

# 在 build_system_prompt 中更新描述
"""
- deploy.deploy: 一键部署 GitHub 项目（自动完成分析→克隆→配置→启动）
  - args: {"repo_url": "https://github.com/owner/repo", "target_dir": "~/projects"}
  - 示例: {"worker": "deploy", "action": "deploy", "args": {"repo_url": "https://github.com/user/app"}, "risk_level": "medium"}
"""
```

#### 1.3.4 测试
```python
# 文件：tests/test_deploy_integration.py

async def test_one_click_deploy_success():
    """测试一键部署成功流程"""
    deploy_worker = DeployWorker(mock_http, mock_shell)
    
    result = await deploy_worker.execute("deploy", {
        "repo_url": "https://github.com/test/repo",
    })
    
    assert result.success
    assert "✅ 部署完成" in result.message
    assert "项目路径" in result.message
    assert result.task_completed

async def test_one_click_deploy_with_error_suggestions():
    """测试部署失败时的建议"""
    # Mock 端口占用错误
    mock_shell.set_error("address already in use: 8080")
    
    result = await deploy_worker.execute("deploy", {
        "repo_url": "https://github.com/test/repo",
    })
    
    assert not result.success
    assert "可能的解决方法" in result.message
    assert "检查端口占用" in result.message
```

**产出**：
- ✅ 新增 `_one_click_deploy` 方法（~150 行）
- ✅ 新增 CLI 命令 `opsai deploy`
- ✅ 智能错误提示机制
- ✅ 更新测试覆盖

---

### Task 1.4：重写 README（5 分钟快速上手）⏱️ 4 小时

**为什么做**：
- 当前 README 太长，新手不知道从哪开始
- 需要"看完前 5 行就能上手"的体验

**具体步骤**：

#### 1.4.1 新的 README 结构
```markdown
# OpsAI - 5 分钟学会运维

> 🚀 用自然语言操作服务器，无需记命令

**核心能力**：查日志 · 查状态 · 重启服务 · 检查资源

## ⚡ 快速开始（3 步上手）

### 1️⃣ 安装
```bash
pip install opsai
```

### 2️⃣ 启动
```bash
opsai-tui
```

### 3️⃣ 试试这 3 个命令
```
> 查看所有容器
> 查看磁盘空间
> 查看最近的日志
```

**[📺 观看 30 秒演示视频](#demo)**

---

## 🎯 常见场景（点击查看示例）

<details>
<summary>🔴 <b>服务出问题了</b></summary>

```bash
# 场景 1：网站打不开
opsai-tui
> "我的网站打不开"
# → 自动检测 nginx 容器状态 + 端口监听 + 查看日志

# 场景 2：查看特定服务日志
> "查看 api-server 的日志"
# → 自动识别容器/systemd 服务，显示最近 100 行日志

# 场景 3：重启服务
> "重启 nginx"
# → 安全确认后执行重启，并验证启动成功
```
</details>

<details>
<summary>💾 <b>磁盘空间不足</b></summary>

```bash
opsai-tui
> "磁盘快满了，帮我清理"
# → 自动查找大文件 + 建议可清理的内容 + 安全删除
```
</details>

<details>
<summary>🚀 <b>部署 GitHub 项目</b></summary>

```bash
# 一键部署（自动检测项目类型）
opsai deploy https://github.com/user/my-app

# 或通过 TUI
opsai-tui
> "帮我部署 https://github.com/user/my-app"
```
</details>

<details>
<summary>🐌 <b>服务响应慢</b></summary>

```bash
opsai-tui
> "服务很慢，帮我看看"
# → 检查 CPU/内存占用 + 分析慢查询日志 + 建议优化方案
```
</details>

---

## 🔒 安全保障

- ✅ **危险操作拦截**：自动识别 `rm -rf`, `kill -9` 等高危命令
- ✅ **二次确认**：破坏性操作需要手动确认
- ✅ **Dry-run 模式**：预览操作，不实际执行
- ✅ **审计日志**：所有操作自动记录到 `~/.opsai/audit.log`

---

## 📖 进阶使用

### 配置 LLM
```bash
# 使用本地 Ollama（推荐）
opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1

# 使用 OpenAI
opsai config set-llm --model gpt-4o --api-key sk-xxx
```

### CLI 模式（快速执行单条命令）
```bash
opsai query "查看磁盘使用情况"
opsai query "列出所有容器" --dry-run
```

### 更多功能
- [智能对象分析](docs/features/analyze.md)（"这个容器是干嘛的"）
- [自定义场景](docs/features/scenarios.md)（保存常用操作）
- [扩展开发](docs/development/extend-workers.md)（添加自定义 Worker）

---

## ❓ 常见问题

**Q: 支持哪些运维工具？**  
A: Docker、Systemd、通用 Shell 命令。未来支持 Kubernetes。

**Q: 需要 root 权限吗？**  
A: 不需要。继承当前用户权限，不涉及提权。

**Q: 数据安全吗？**  
A: 所有数据在本地处理，不上传到云端（LLM API 除外）。

**Q: 如何卸载？**  
A: `pip uninstall opsai` + 删除 `~/.opsai/` 目录。

---

## 🤝 贡献

欢迎提交 Issue 和 PR！详见 [贡献指南](CONTRIBUTING.md)。

## 📄 开源协议

MIT License
```

#### 1.4.2 录制演示视频
```bash
# 使用 asciinema 录制终端操作
asciinema rec demo.cast

# 操作流程：
1. opsai-tui
2. 输入"查看所有容器"
3. 输入"这个是干嘛的"（指代解析演示）
4. 输入"查看日志"
5. 退出

# 转换为 GIF
agg demo.cast demo.gif
```

#### 1.4.3 新增快速上手文档
```bash
# 创建 docs/quickstart/
mkdir -p docs/quickstart
touch docs/quickstart/5min-guide.md
touch docs/quickstart/scenarios.md
touch docs/quickstart/faq.md
```

**产出**：
- ✅ 精简 README（从 200 行 → 100 行）
- ✅ 30 秒演示视频/GIF
- ✅ 场景化示例（折叠式展示）

---

### Task 1.5：测试与发布 ⏱️ 4 小时

#### 1.5.1 回归测试
```bash
# 运行所有测试
uv run pytest -v --cov=src --cov-report=html

# 检查覆盖率（目标 > 80%）
open htmlcov/index.html

# 类型检查
uv run mypy src/

# 代码格式
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

#### 1.5.2 手动测试清单
```
☐ 安装体验：pip install opsai
☐ 首次运行：opsai-tui（检查是否报错）
☐ 核心场景：
  ☐ 查看容器列表
  ☐ 查看日志
  ☐ 重启服务
  ☐ 检查磁盘
☐ 一键部署：opsai deploy <github-url>
☐ Dry-run 模式：--dry-run 参数
☐ 配置管理：opsai config show
```

#### 1.5.3 发布 v0.2.0
```bash
# 更新版本号
# pyproject.toml: version = "0.2.0"

# 编写 CHANGELOG
cat > CHANGELOG.md << 'EOF'
# Changelog

## [0.2.0] - 2026-02-XX

### 🚀 新增
- 一键部署 GitHub 项目（`opsai deploy <url>`）
- 智能错误提示（失败时提供可操作建议）

### ✨ 优化
- 精简 Workers 数量（10 → 7 个）
- 简化 README，新增"5 分钟快速上手"
- 内置缓存逻辑（移除独立 CacheWorker）

### 🗑️ 移除
- 移除 Tavily 搜索依赖（减少外部依赖）

### 🐛 修复
- 修复 analyze 指代解析问题
- 修复 dry-run 模式下的日志记录

### 📝 文档
- 新增演示视频
- 新增场景化示例
- 新增 FAQ 文档
EOF

# 构建发布
uv build
uv publish  # 或 twine upload dist/*
```

**产出**：
- ✅ 测试覆盖率 > 80%
- ✅ 发布 v0.2.0
- ✅ 更新 CHANGELOG

---

## 🎨 P1 阶段：体验优化（第 3-6 周）

**目标**：让新手在 5 分钟内能独立完成核心操作

### Task 2.1：首次运行引导 ⏱️ 12 小时

**为什么做**：
- 新手不知道从哪开始
- 需要"手把手教"的体验

**具体步骤**：

#### 2.1.1 环境检测器
```python
# 文件：src/context/detector.py (新建)

from typing import Optional
import subprocess
from dataclasses import dataclass

@dataclass
class EnvironmentInfo:
    """环境信息"""
    has_docker: bool
    docker_containers: int
    has_systemd: bool
    systemd_services: list[str]
    has_kubernetes: bool
    disk_usage: float  # 百分比
    memory_usage: float

class EnvironmentDetector:
    """环境检测器"""
    
    def detect(self) -> EnvironmentInfo:
        """检测当前环境"""
        return EnvironmentInfo(
            has_docker=self._check_docker(),
            docker_containers=self._count_containers(),
            has_systemd=self._check_systemd(),
            systemd_services=self._list_important_services(),
            has_kubernetes=self._check_kubernetes(),
            disk_usage=self._get_disk_usage(),
            memory_usage=self._get_memory_usage(),
        )
    
    def _check_docker(self) -> bool:
        """检查 Docker 是否运行"""
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _count_containers(self) -> int:
        """统计容器数量"""
        if not self._check_docker():
            return 0
        try:
            result = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        except Exception:
            return 0
    
    def _check_systemd(self) -> bool:
        """检查 Systemd 是否可用"""
        try:
            result = subprocess.run(
                ["systemctl", "--version"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _list_important_services(self) -> list[str]:
        """列出重要的 systemd 服务"""
        if not self._check_systemd():
            return []
        
        important_services = [
            "nginx", "apache2", "httpd",
            "mysql", "postgresql",
            "redis", "mongodb",
        ]
        
        running = []
        for service in important_services:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                if result.stdout.strip() == "active":
                    running.append(service)
            except Exception:
                pass
        
        return running
    
    def _check_kubernetes(self) -> bool:
        """检查 Kubernetes 是否可用"""
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _get_disk_usage(self) -> float:
        """获取根目录磁盘使用率"""
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    usage_str = parts[4].rstrip("%")
                    return float(usage_str)
        except Exception:
            pass
        return 0.0
    
    def _get_memory_usage(self) -> float:
        """获取内存使用率"""
        try:
            result = subprocess.run(
                ["free", "-m"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 3:
                    total = float(parts[1])
                    used = float(parts[2])
                    return (used / total) * 100
        except Exception:
            pass
        return 0.0
```

#### 2.1.2 欢迎界面
```python
# 文件：src/tui.py

from src.context.detector import EnvironmentDetector, EnvironmentInfo

class OpsAIApp(App):
    
    def on_mount(self) -> None:
        """应用启动时"""
        # 检查是否首次运行
        if self._is_first_run():
            self.show_welcome_wizard()
    
    def _is_first_run(self) -> bool:
        """检查是否首次运行"""
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        return not marker_file.exists()
    
    def _mark_first_run_complete(self) -> None:
        """标记首次运行已完成"""
        marker_file = Path.home() / ".opsai" / ".first_run_complete"
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.touch()
    
    def show_welcome_wizard(self) -> None:
        """显示欢迎向导"""
        detector = EnvironmentDetector()
        env_info = detector.detect()
        
        # 构建欢迎消息
        welcome_parts = [
            "🎉 欢迎使用 OpsAI！",
            "",
            "我已经检测到你的环境：",
        ]
        
        # Docker 信息
        if env_info.has_docker:
            welcome_parts.append(f"✓ Docker 正在运行 ({env_info.docker_containers} 个容器)")
        else:
            welcome_parts.append("✗ Docker 未运行")
        
        # Systemd 信息
        if env_info.has_systemd:
            if env_info.systemd_services:
                services_str = ", ".join(env_info.systemd_services[:3])
                welcome_parts.append(f"✓ Systemd 服务：{services_str}...")
            else:
                welcome_parts.append("✓ Systemd 服务管理器")
        
        # Kubernetes 信息
        if env_info.has_kubernetes:
            welcome_parts.append("✓ Kubernetes (kubectl)")
        
        # 资源警告
        welcome_parts.append("")
        if env_info.disk_usage > 80:
            welcome_parts.append(f"⚠️  磁盘使用率 {env_info.disk_usage:.0f}%（建议清理）")
        
        if env_info.memory_usage > 80:
            welcome_parts.append(f"⚠️  内存使用率 {env_info.memory_usage:.0f}%")
        
        # 推荐操作
        welcome_parts.extend([
            "",
            "推荐你试试这些操作：",
        ])
        
        suggestions = self._generate_suggestions(env_info)
        for i, suggestion in enumerate(suggestions, 1):
            welcome_parts.append(f"{i}️⃣  {suggestion}")
        
        welcome_parts.extend([
            "",
            "💡 提示：直接用自然语言描述你的需求即可",
            "   例如："查看日志"、"重启服务"、"磁盘快满了"",
        ])
        
        # 显示欢迎面板
        welcome_msg = "\n".join(welcome_parts)
        self.add_message("system", welcome_msg)
        
        # 标记首次运行完成
        self._mark_first_run_complete()
    
    def _generate_suggestions(self, env_info: EnvironmentInfo) -> list[str]:
        """根据环境生成操作建议"""
        suggestions = []
        
        if env_info.has_docker and env_info.docker_containers > 0:
            suggestions.append("查看所有容器状态")
        
        if env_info.disk_usage > 70:
            suggestions.append("查看磁盘使用情况")
        
        if env_info.systemd_services:
            suggestions.append(f"查看 {env_info.systemd_services[0]} 服务日志")
        elif env_info.has_docker:
            suggestions.append("查看容器日志")
        else:
            suggestions.append("查看系统日志")
        
        # 至少提供 3 个建议
        if len(suggestions) < 3:
            suggestions.append("检查系统资源占用")
        
        return suggestions[:3]
```

#### 2.1.3 测试
```python
# 文件：tests/test_welcome_wizard.py

def test_environment_detection():
    """测试环境检测"""
    detector = EnvironmentDetector()
    env_info = detector.detect()
    
    assert isinstance(env_info.has_docker, bool)
    assert env_info.docker_containers >= 0
    assert env_info.disk_usage >= 0

def test_first_run_detection():
    """测试首次运行检测"""
    # 删除标记文件
    marker_file = Path.home() / ".opsai" / ".first_run_complete"
    if marker_file.exists():
        marker_file.unlink()
    
    app = OpsAIApp()
    assert app._is_first_run()
    
    app._mark_first_run_complete()
    assert not app._is_first_run()
```

**产出**：
- ✅ 环境自动检测
- ✅ 智能操作推荐
- ✅ 首次运行引导

---

### Task 2.2：场景推荐系统 ⏱️ 16 小时

**具体步骤**：

#### 2.2.1 场景定义
```python
# 文件：src/orchestrator/scenarios.py (新建)

from dataclasses import dataclass
from typing import Optional

@dataclass
class Scenario:
    """运维场景"""
    id: str
    title: str
    description: str
    category: str  # troubleshooting, maintenance, deployment, monitoring
    icon: str
    steps: list[dict[str, str]]  # [{"prompt": "...", "description": "..."}]
    risk_level: str  # safe, medium, high

# 预置场景库
SCENARIOS: list[Scenario] = [
    Scenario(
        id="service_down",
        title="服务无响应",
        description="网站/API 打不开，快速诊断和修复",
        category="troubleshooting",
        icon="🔴",
        steps=[
            {"prompt": "列出所有容器", "description": "检查服务是否运行"},
            {"prompt": "查看日志", "description": "查找错误信息"},
            {"prompt": "重启服务", "description": "尝试恢复服务"},
        ],
        risk_level="medium",
    ),
    Scenario(
        id="disk_full",
        title="磁盘空间不足",
        description="清理大文件和日志，释放磁盘空间",
        category="maintenance",
        icon="💾",
        steps=[
            {"prompt": "查看磁盘使用情况", "description": "定位占用高的目录"},
            {"prompt": "查找大文件", "description": "找出可清理的文件"},
            {"prompt": "清理日志", "description": "删除旧日志文件"},
        ],
        risk_level="medium",
    ),
    Scenario(
        id="high_cpu",
        title="CPU 占用过高",
        description="排查资源占用，优化性能",
        category="troubleshooting",
        icon="🔥",
        steps=[
            {"prompt": "查看进程 CPU 占用", "description": "找出占用最高的进程"},
            {"prompt": "分析进程详情", "description": "了解进程用途"},
            {"prompt": "重启高占用服务", "description": "尝试恢复正常"},
        ],
        risk_level="medium",
    ),
    Scenario(
        id="deploy_github",
        title="部署 GitHub 项目",
        description="一键部署开源项目到服务器",
        category="deployment",
        icon="🚀",
        steps=[
            {"prompt": "部署项目", "description": "自动克隆、配置、启动"},
        ],
        risk_level="medium",
    ),
    Scenario(
        id="check_logs",
        title="查看服务日志",
        description="快速定位错误和异常",
        category="monitoring",
        icon="📋",
        steps=[
            {"prompt": "列出所有服务", "description": "选择要查看的服务"},
            {"prompt": "查看日志", "description": "显示最近的日志"},
        ],
        risk_level="safe",
    ),
]

class ScenarioManager:
    """场景管理器"""
    
    def __init__(self):
        self._scenarios = {s.id: s for s in SCENARIOS}
    
    def get_by_id(self, scenario_id: str) -> Optional[Scenario]:
        """根据 ID 获取场景"""
        return self._scenarios.get(scenario_id)
    
    def get_by_category(self, category: str) -> list[Scenario]:
        """根据分类获取场景"""
        return [s for s in SCENARIOS if s.category == category]
    
    def get_all(self) -> list[Scenario]:
        """获取所有场景"""
        return SCENARIOS
    
    def recommend(self, env_info: EnvironmentInfo) -> list[Scenario]:
        """根据环境推荐场景"""
        recommendations = []
        
        # 磁盘告警 → 推荐清理场景
        if env_info.disk_usage > 80:
            recommendations.append(self.get_by_id("disk_full"))
        
        # 有 Docker 容器 → 推荐服务管理
        if env_info.has_docker and env_info.docker_containers > 0:
            recommendations.append(self.get_by_id("service_down"))
            recommendations.append(self.get_by_id("check_logs"))
        
        # 默认推荐
        if not recommendations:
            recommendations.extend([
                self.get_by_id("check_logs"),
                self.get_by_id("deploy_github"),
            ])
        
        return [s for s in recommendations if s]  # 过滤 None
```

#### 2.2.2 TUI 场景界面
```python
# 文件：src/tui.py

from src.orchestrator.scenarios import ScenarioManager

class OpsAIApp(App):
    
    def __init__(self):
        super().__init__()
        self._scenario_manager = ScenarioManager()
    
    def show_scenarios(self) -> None:
        """显示场景列表"""
        scenarios = self._scenario_manager.get_all()
        
        # 按分类组织
        categories = {
            "troubleshooting": "🔴 故障排查",
            "maintenance": "🛠️  日常维护",
            "deployment": "🚀 项目部署",
            "monitoring": "📊 监控查看",
        }
        
        message_parts = ["═══ 常见运维场景 ═══\n"]
        
        for cat_id, cat_name in categories.items():
            cat_scenarios = self._scenario_manager.get_by_category(cat_id)
            if not cat_scenarios:
                continue
            
            message_parts.append(f"\n{cat_name}")
            for scenario in cat_scenarios:
                risk_badge = {
                    "safe": "🟢",
                    "medium": "🟡",
                    "high": "🔴",
                }.get(scenario.risk_level, "")
                
                message_parts.append(
                    f"  {scenario.icon} [{scenario.id}] {scenario.title} {risk_badge}"
                )
                message_parts.append(f"     {scenario.description}")
        
        message_parts.extend([
            "",
            "💡 使用方法：",
            "   - 输入场景 ID（如 'service_down'）快速执行",
            "   - 或直接描述你的问题（如 '服务打不开'）",
        ])
        
        self.add_message("system", "\n".join(message_parts))
    
    async def handle_input(self, user_input: str) -> None:
        """处理用户输入"""
        # 检查是否是场景 ID
        scenario = self._scenario_manager.get_by_id(user_input.strip().lower())
        if scenario:
            await self._execute_scenario(scenario)
            return
        
        # 否则走正常的 LLM 处理流程
        await self._process_normal_query(user_input)
    
    async def _execute_scenario(self, scenario: Scenario) -> None:
        """执行场景"""
        self.add_message("system", f"开始执行场景：{scenario.icon} {scenario.title}")
        
        for i, step in enumerate(scenario.steps, 1):
            self.add_message("system", f"Step {i}/{len(scenario.steps)}: {step['description']}")
            
            # 执行步骤
            await self._process_normal_query(step["prompt"])
            
            # 检查是否需要用户确认继续
            if i < len(scenario.steps):
                # TODO: 添加"继续下一步"的确认逻辑
                pass
        
        self.add_message("system", f"✅ 场景执行完成：{scenario.title}")
```

#### 2.2.3 CLI 场景命令
```python
# 文件：src/cli.py

@app.command()
def scenarios():
    """列出所有可用场景"""
    from src.orchestrator.scenarios import ScenarioManager
    from rich.table import Table
    
    console = Console()
    manager = ScenarioManager()
    
    table = Table(title="OpsAI 运维场景")
    table.add_column("ID", style="cyan")
    table.add_column("标题", style="green")
    table.add_column("描述")
    table.add_column("风险", justify="center")
    
    for scenario in manager.get_all():
        risk_badge = {
            "safe": "🟢 安全",
            "medium": "🟡 中等",
            "high": "🔴 高危",
        }.get(scenario.risk_level, "")
        
        table.add_row(
            scenario.id,
            f"{scenario.icon} {scenario.title}",
            scenario.description,
            risk_badge,
        )
    
    console.print(table)
    console.print("\n💡 使用 [cyan]opsai scenario <id>[/cyan] 执行场景")

@app.command()
def scenario(
    scenario_id: str = typer.Argument(..., help="场景 ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="模拟执行"),
):
    """执行预定义场景
    
    示例：
        opsai scenario disk_full
        opsai scenario service_down --dry-run
    """
    from src.orchestrator.scenarios import ScenarioManager
    
    console = Console()
    manager = ScenarioManager()
    
    scenario = manager.get_by_id(scenario_id)
    if not scenario:
        console.print(f"[red]错误：未找到场景 '{scenario_id}'[/red]")
        console.print("使用 [cyan]opsai scenarios[/cyan] 查看所有可用场景")
        raise typer.Exit(code=1)
    
    console.print(Panel(
        f"{scenario.icon} {scenario.title}\n\n{scenario.description}",
        title="执行场景",
        border_style="green",
    ))
    
    # 执行场景步骤
    for i, step in enumerate(scenario.steps, 1):
        console.print(f"\n[bold]Step {i}/{len(scenario.steps)}:[/bold] {step['description']}")
        
        # 调用 query 命令执行步骤
        # TODO: 实现步骤执行逻辑
        console.print(f"  执行: {step['prompt']}")
```

**产出**：
- ✅ 5 个预置场景
- ✅ TUI 场景界面
- ✅ CLI 场景命令
- ✅ 智能场景推荐

---

### Task 2.3：智能错误提示 ⏱️ 8 小时

**具体步骤**：

#### 2.3.1 错误分析器
```python
# 文件：src/orchestrator/error_helper.py (新建)

from typing import Optional
from src.types import WorkerResult

class ErrorHelper:
    """错误提示助手"""
    
    def suggest_fix(self, result: WorkerResult, user_input: str) -> Optional[str]:
        """根据错误结果生成建议
        
        Args:
            result: Worker 执行结果
            user_input: 用户原始输入
        
        Returns:
            建议文本（如果有）
        """
        if result.success:
            return None
        
        error_msg = result.message.lower()
        suggestions = []
        
        # 容器未找到
        if "not found" in error_msg and ("container" in error_msg or "docker" in error_msg):
            suggestions.extend([
                "💡 可能的原因：",
                "  1. 容器名称错误，使用以下命令查看所有容器：",
                "     opsai query \"列出所有容器\"",
                "  2. 如果是 systemd 服务，尝试：",
                "     opsai query \"查看 服务名.service 状态\"",
                "  3. 如果是进程，尝试：",
                "     opsai query \"查看进程列表\"",
            ])
        
        # 权限不足
        elif "permission denied" in error_msg:
            suggestions.extend([
                "💡 权限不足，尝试以下方法：",
                "  1. 检查文件/目录权限：",
                "     ls -la <文件路径>",
                "  2. 如果需要 root 权限，使用 sudo：",
                "     sudo opsai query \"...\"",
                "  3. 对于 Docker，确保用户在 docker 组：",
                "     sudo usermod -aG docker $USER",
            ])
        
        # 端口占用
        elif "address already in use" in error_msg or "port" in error_msg:
            # 尝试从错误信息提取端口号
            import re
            port_match = re.search(r":(\d+)", error_msg)
            port = port_match.group(1) if port_match else "端口号"
            
            suggestions.extend([
                f"💡 端口 {port} 已被占用，尝试以下方法：",
                f"  1. 查看占用端口的进程：",
                f"     opsai query \"查看 {port} 端口占用\"",
                f"  2. 停止占用进程后重试",
                f"  3. 修改服务配置，使用其他端口",
            ])
        
        # 文件不存在
        elif "no such file" in error_msg or "not found" in error_msg:
            suggestions.extend([
                "💡 文件/目录不存在，尝试以下方法：",
                "  1. 检查路径是否正确（注意大小写）",
                "  2. 查看当前目录内容：",
                "     opsai query \"列出当前目录文件\"",
                "  3. 搜索文件位置：",
                "     opsai query \"查找文件 <文件名>\"",
            ])
        
        # Docker 未运行
        elif "cannot connect to the docker daemon" in error_msg:
            suggestions.extend([
                "💡 Docker 未运行，尝试以下方法：",
                "  1. 启动 Docker：",
                "     sudo systemctl start docker",
                "  2. 检查 Docker 状态：",
                "     sudo systemctl status docker",
                "  3. 如果是 macOS/Windows，启动 Docker Desktop",
            ])
        
        # 命令未找到
        elif "command not found" in error_msg:
            cmd_match = re.search(r"command not found: (\w+)", error_msg)
            cmd = cmd_match.group(1) if cmd_match else "命令"
            
            suggestions.extend([
                f"💡 命令 '{cmd}' 未安装，尝试以下方法：",
                f"  1. 安装命令（根据系统）：",
                f"     apt install {cmd}  # Debian/Ubuntu",
                f"     yum install {cmd}  # CentOS/RHEL",
                f"     brew install {cmd}  # macOS",
                f"  2. 检查命令是否在 PATH 中",
            ])
        
        # 通用建议
        if not suggestions:
            suggestions.extend([
                "💡 操作失败，建议：",
                "  1. 检查输入是否正确",
                "  2. 使用 --dry-run 预览操作",
                "  3. 查看审计日志了解详情：",
                "     cat ~/.opsai/audit.log",
            ])
        
        return "\n".join(suggestions)
```

#### 2.3.2 集成到 Orchestrator
```python
# 文件：src/orchestrator/engine.py

from src.orchestrator.error_helper import ErrorHelper

class Orchestrator:
    
    def __init__(self, ...):
        # ...
        self._error_helper = ErrorHelper()
    
    async def react_loop(self, user_input: str, ...) -> WorkerResult:
        # ... 原有逻辑 ...
        
        # 执行 Worker
        result = await worker.execute(action, args)
        
        # 如果失败，生成建议
        if not result.success:
            suggestions = self._error_helper.suggest_fix(result, user_input)
            if suggestions:
                # 将建议附加到错误消息
                result.message = f"{result.message}\n\n{suggestions}"
        
        return result
```

**产出**：
- ✅ 智能错误提示
- ✅ 7 种常见错误场景覆盖
- ✅ 可操作的建议

---

### Task 2.4：文档优化 ⏱️ 8 小时

#### 2.4.1 创建快速上手文档
```bash
mkdir -p docs/quickstart
```

```markdown
# 文件：docs/quickstart/5min-guide.md

# 5 分钟快速上手指南

## 第 1 分钟：安装

```bash
pip install opsai
```

## 第 2 分钟：启动

```bash
opsai-tui
```

你会看到欢迎界面，显示检测到的环境信息。

## 第 3 分钟：试试这 3 个命令

### 1. 查看所有容器
```
> 查看所有容器
```

### 2. 查看磁盘空间
```
> 查看磁盘使用情况
```

### 3. 查看日志
```
> 查看最近的日志
```

## 第 4 分钟：尝试指代解析

```
> 列出所有容器
> 这个是干嘛的  ← 自动解析为上一步的容器
```

## 第 5 分钟：探索场景

```
> scenarios  ← 查看所有预置场景
> service_down  ← 执行"服务无响应"场景
```

---

## 下一步

- [常见场景示例](scenarios.md)
- [配置 LLM](../configuration/llm.md)
- [安全机制详解](../features/safety.md)
```

#### 2.4.2 场景示例文档
```markdown
# 文件：docs/quickstart/scenarios.md

# 常见运维场景

## 🔴 场景 1：服务无响应

**问题**：网站/API 打不开

**操作步骤**：

```bash
# 方式 1：使用场景 ID
opsai scenario service_down

# 方式 2：自然语言描述
opsai-tui
> "我的网站打不开了"
```

**自动执行**：
1. 检查容器/进程状态
2. 查看最近的错误日志
3. 询问是否重启服务

---

## 💾 场景 2：磁盘空间不足

**问题**：服务器提示 "No space left on device"

**操作步骤**：

```bash
opsai scenario disk_full
```

**自动执行**：
1. 查看各分区使用情况
2. 查找大于 100MB 的文件
3. 建议可清理的日志/临时文件
4. 询问是否执行清理

---

## 🐌 场景 3：服务响应慢

**问题**：API 响应时间从 100ms 增加到 5s

**操作步骤**：

```bash
opsai-tui
> "服务很慢，帮我看看"
```

**自动执行**：
1. 检查 CPU/内存占用
2. 查看容器资源限制
3. 分析日志中的慢查询
4. 建议优化方案（重启/扩容/优化）

---

## 🚀 场景 4：部署 GitHub 项目

**问题**：想快速部署一个开源项目

**操作步骤**：

```bash
# 一键部署
opsai deploy https://github.com/user/my-app

# 或通过 TUI
opsai-tui
> "帮我部署 https://github.com/user/my-app"
```

**自动执行**：
1. 分析项目类型（Docker/Python/Node.js）
2. 克隆仓库
3. 安装依赖
4. 启动服务

---

## 📋 场景 5：查看服务日志

**问题**：需要排查错误，但不记得日志路径

**操作步骤**：

```bash
opsai-tui
> "查看 api-server 的日志"
```

**自动执行**：
1. 自动识别服务类型（Docker/Systemd）
2. 获取最近 100 行日志
3. 高亮错误/警告信息
```

#### 2.4.3 FAQ 文档
```markdown
# 文件：docs/quickstart/faq.md

# 常见问题

## 安装与配置

### Q: 如何安装 OpsAI？
```bash
pip install opsai
```

### Q: 支持哪些 Python 版本？
Python 3.9 及以上。

### Q: 如何配置 LLM？

**使用本地 Ollama（推荐）**：
```bash
# 1. 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. 拉取模型
ollama pull qwen2.5:7b

# 3. 配置 OpsAI
opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1
```

**使用 OpenAI**：
```bash
opsai config set-llm --model gpt-4o --api-key sk-xxx
```

---

## 使用问题

### Q: 支持哪些运维工具？
- ✅ Docker（容器管理）
- ✅ Systemd（服务管理）
- ✅ 通用 Shell 命令
- 🚧 Kubernetes（开发中）

### Q: 需要 root 权限吗？
不需要。OpsAI 继承当前用户权限，不涉及提权操作。

### Q: 数据安全吗？
- 所有命令在本地执行
- 审计日志存储在 `~/.opsai/audit.log`
- 仅 LLM API 调用会发送数据（符合各 API 提供商的隐私政策）

### Q: 如何查看历史操作？
```bash
# 查看审计日志
cat ~/.opsai/audit.log

# 或在 TUI 中查看对话历史
opsai-tui → 按上下箭头查看
```

---

## 功能问题

### Q: 如何撤销误操作？
OpsAI 不提供自动撤销功能，建议：
1. 使用 `--dry-run` 预览操作
2. 对于破坏性操作，会强制二次确认
3. 查看审计日志了解具体执行的命令

### Q: Dry-run 模式是什么？
模拟执行模式，显示将要执行的操作但不实际执行。

```bash
# CLI 模式
opsai query "删除临时文件" --dry-run

# TUI 模式会自动提示高危操作
```

### Q: 如何自定义场景？
场景存储在 `~/.opsai/scenarios/`，格式为 JSON：

```json
{
  "id": "my_scenario",
  "title": "我的自定义场景",
  "description": "描述",
  "category": "custom",
  "icon": "🎯",
  "steps": [
    {"prompt": "查看状态", "description": "检查服务"}
  ],
  "risk_level": "safe"
}
```

---

## 故障排除

### Q: 提示 "LLM connection failed"
1. 检查 LLM 配置：`opsai config show`
2. 测试连接：`curl http://localhost:11434/v1/models`（Ollama）
3. 查看错误日志：`~/.opsai/debug.log`

### Q: 提示 "Docker daemon not running"
1. 启动 Docker：`sudo systemctl start docker`
2. 检查状态：`sudo systemctl status docker`
3. 如果是 macOS/Windows，启动 Docker Desktop

### Q: 如何卸载？
```bash
# 1. 卸载 Python 包
pip uninstall opsai

# 2. 删除配置文件
rm -rf ~/.opsai/
```

---

## 贡献与支持

### Q: 如何报告 Bug？
在 GitHub 提交 Issue：https://github.com/yourusername/opsai/issues

### Q: 如何贡献代码？
参见 [贡献指南](../CONTRIBUTING.md)

### Q: 如何联系开发者？
- GitHub Issues
- Email: your-email@example.com
```

**产出**：
- ✅ 5 分钟快速上手指南
- ✅ 场景示例文档
- ✅ FAQ 文档

---

## 🚀 P2 阶段：功能增强（第 7-8 周，可选）

### Task 3.1：TUI 可视化增强 ⏱️ 16 小时

**具体内容**：
- 容器/进程列表用表格展示（使用 rich.table）
- 日志高亮关键词（ERROR, WARN, Exception）
- 资源占用用进度条展示（CPU/内存/磁盘）

### Task 3.2：历史记录和收藏 ⏱️ 12 小时

**具体内容**：
- 保存常用操作为书签
- 快速调用历史命令
- 导出/导入书签配置

---

## 📊 验收标准

### P0 阶段验收
- [ ] 代码行数减少 > 500 行
- [ ] Workers 数量：10 → 7
- [ ] 外部依赖减少：1 个（tavily-python）
- [ ] 新增 CLI 命令：`opsai deploy`
- [ ] README 长度：200 行 → 100 行
- [ ] 测试覆盖率 > 80%

### P1 阶段验收
- [ ] 首次运行显示欢迎界面
- [ ] 环境自动检测准确率 > 90%
- [ ] 预置场景数量 >= 5 个
- [ ] 错误提示覆盖 7 种常见场景
- [ ] 新增快速上手文档 3 篇

### P2 阶段验收
- [ ] TUI 支持表格展示
- [ ] 日志高亮功能
- [ ] 书签系统可用

---

## 🎯 成功指标

**产品目标**：让不懂运维的人，在 5 分钟内能独立完成：

1. ✅ 查看服务状态（目标：< 3 分钟）
2. ✅ 查看日志找问题（目标：< 5 分钟）
3. ✅ 重启服务解决故障（目标：< 5 分钟）

**衡量方式**：
- 邀请 5-10 个"不懂运维的用户"试用
- 记录首次成功操作时间
- 收集用户反馈和改进建议

---

## 📝 总结

**总工期**：6-8 周  
**核心原则**：减法而非加法，场景而非功能，引导而非文档

**关键里程碑**：
- Week 2: 发布 v0.2.0（核心精简版）
- Week 4: 发布 v0.3.0（体验优化版）
- Week 6: 发布 v0.4.0（功能增强版）

**下一步**：
建议先完成 P0 阶段（第 1-2 周），然后邀请真实用户试用，根据反馈调整 P1/P2 的优先级。
