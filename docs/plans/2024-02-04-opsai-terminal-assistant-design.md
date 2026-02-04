# OpsAI 终端智能助手 - 技术设计文档

**项目愿景:** 打造一个"懂意图、知环境、守安全"的终端智能助手,通过自然语言降低复杂运维任务的门槛,实现从"查文档写脚本"到"对话即交付"的转变。

**设计日期:** 2024-02-04
**架构模式:** Orchestrator-Workers (ReAct Loop)
**技术栈:** Python 3.9+, Textual, Typer, LiteLLM, Docker SDK

---

## 一、系统架构与数据流

### 1.1 核心架构

系统采用 **Orchestrator-Workers** 模式,明确分离"思考"与"执行":

```
用户输入 → Orchestrator (LLM 引擎) → Worker Pool → 系统调用
         ↑                             ↓
         └──────── ReAct 循环 ──────────┘
```

**Orchestrator 职责:**
- 接收用户自然语言指令
- 调用 LLM(通过 LiteLLM)生成结构化 JSON 指令
- 执行安全检查(高危操作拦截)
- 实现 ReAct 循环(Reason-Act):根据 Worker 返回结果决定下一步动作

**Worker Pool 职责:**
- `SystemWorker`: 文件系统操作(基于 `os`, `shutil`, `pathlib`)
- `ContainerWorker`: Docker 容器管理(基于 `docker-py`)
- `AuditWorker`: 审计日志写入(追加式文本文件)

### 1.2 标准化数据结构

**Orchestrator → Worker 指令格式(扁平结构):**
```python
{
  "worker": "system",           # 目标 Worker 标识符
  "action": "find_large_files", # 动作名称
  "args": {                     # 参数字典
    "path": "/var/log",
    "min_size_mb": 100
  },
  "risk_level": "safe" | "medium" | "high"
}
```

**Worker → Orchestrator 返回格式:**
```python
{
  "success": True,              # 执行是否成功
  "data": [...],                # 结构化结果数据
  "message": "Found 3 files",   # 人类可读描述
  "task_completed": False       # 任务是否完成(控制 ReAct 循环)
}
```

**设计原则:**
- 扁平指令流,无依赖关系嵌套(消除特殊情况)
- Worker 保持"愚蠢"状态,仅负责执行,不负责推理
- 多步任务通过 Orchestrator 的 ReAct 循环自然实现

---

## 二、安全机制设计

### 2.1 三层防护体系

**Layer 1: Orchestrator 集中式拦截**
```python
# src/orchestrator/safety.py
DANGER_PATTERNS = {
    "high": ["rm -rf", "kill -9", "format", "dd if=", "> /dev/"],
    "medium": ["rm ", "kill", "docker rm", "systemctl stop"]
}

def check_safety(instruction: dict) -> str:
    """返回 risk_level: safe | medium | high"""
    command_text = f"{instruction['action']} {instruction['args']}"
    for level, patterns in DANGER_PATTERNS.items():
        if any(p in command_text for p in patterns):
            return level
    return "safe"
```

**Layer 2: Human-in-the-loop 强制确认**
```python
# TUI 流程
if risk_level in ["medium", "high"]:
    display_warning_dialog(
        command=generated_command,
        risk=risk_level,
        affected_files=preview_affected_resources()
    )
    user_choice = await wait_for_confirmation()  # 阻塞等待
    if user_choice != "CONFIRM":
        log_rejection()
        return
```

**Layer 3: 审计日志(不可篡改记录)**
```
# ~/.opsai/audit.log 格式
[时间戳] INPUT: <原始指令> | WORKER: <worker>.<action> | RISK: <level> | CONFIRMED: <yes/no> | EXIT: <code> | OUTPUT: <前100字符>

示例:
[2024-02-04 10:30:15] INPUT: "清理 /var/log 大文件" | WORKER: system.delete_files | RISK: high | CONFIRMED: yes | EXIT: 0 | OUTPUT: Deleted 3 files (total 500MB)
```

### 2.2 关键设计原则

- 安全检查集中在 Orchestrator,不散落在各个 Worker
- 高危操作**必须**通过 TUI 模式确认,CLI 模式自动拒绝
- 所有操作(包括被拒绝的)都记录到审计日志
- 审计日志采用追加式文本文件,便于 `grep` 和 `tail` 分析

---

## 三、环境感知与上下文注入

### 3.1 启动时环境收集

```python
# src/context/environment.py
class EnvironmentContext:
    def __init__(self):
        self.os_type = platform.system()        # Darwin/Linux/Windows
        self.os_version = platform.release()
        self.shell = os.environ.get('SHELL', 'unknown')
        self.cwd = os.getcwd()
        self.user = os.environ.get('USER')
        self.docker_available = self._check_docker()
        self.timestamp = datetime.now().isoformat()

    def _check_docker(self) -> bool:
        try:
            subprocess.run(['docker', 'info'],
                         capture_output=True, timeout=2)
            return True
        except:
            return False

    def to_prompt_context(self) -> str:
        """转换为 LLM Prompt 的上下文字符串"""
        return f"""
Current Environment:
- OS: {self.os_type} {self.os_version}
- Shell: {self.shell}
- Working Directory: {self.cwd}
- Docker: {'Available' if self.docker_available else 'Not available'}
- User: {self.user}
"""
```

### 3.2 Prompt 模板设计

```python
# 每次 LLM 调用的完整 Prompt
SYSTEM_PROMPT = """
You are an ops automation assistant. Generate JSON instructions to solve user's task.

{environment_context}

Available Workers:
- system: find_large_files, delete_files, check_disk_usage
- container: list_containers, restart_container, view_logs

Output format:
{{"worker": "...", "action": "...", "args": {{...}}, "risk_level": "safe|medium|high"}}
"""

user_prompt = f"User request: {user_input}"
```

### 3.3 设计决策

- 环境信息在 CLI/TUI 启动时收集一次,会话期间不再更新
- 避免为"用户可能在会话中切换目录"的假想场景增加复杂度
- 所有环境数据注入到 LLM 的 System Prompt,帮助 LLM 生成正确指令

---

## 四、双模交互界面设计

### 4.1 CLI 模式(快速单次执行)

**基本用法:**
```bash
opsai "查找占用空间最大的 10 个文件"
```

**执行流程示例:**
```bash
$ opsai "清理 /tmp 下 7 天前的文件"
[Analyzing] Understanding your request...
[Planning] Will execute: find /tmp -mtime +7 -type f -delete
[Safety Check] Risk Level: HIGH - requires confirmation
Error: High-risk operations require TUI mode for confirmation.
Run: opsai-tui
```

**CLI 模式限制:**
- 仅支持 `safe` 级别操作自动执行
- `medium/high` 风险操作自动拒绝,提示用户切换到 TUI
- 适用场景:快速查询类操作(disk usage, list files, docker ps)

### 4.2 TUI 模式(交互式会话)

**界面布局(基于 Textual 框架):**
```
┌─────────────────────────────────────────┐
│ OpsAI Terminal Assistant                │
├─────────────────────────────────────────┤
│ [对话历史区域]                           │
│ User: 清理 /var/log 大文件               │
│ Assistant: 找到 3 个超过 100MB 的文件:   │
│   - /var/log/syslog.1 (250MB)          │
│   - /var/log/nginx/access.log (180MB)  │
│                                         │
│ ⚠️  Confirm deletion? [Yes] [No]        │
├─────────────────────────────────────────┤
│ > 输入框_                                │
└─────────────────────────────────────────┘
```

**TUI 核心功能:**
- 流式显示 LLM 思考过程(ReAct 循环可视化)
- 高危操作弹出模态确认对话框
- 支持上下文连续对话(多轮任务拆解)
- 实时显示 Worker 执行进度

---

## 五、ReAct 循环与多步任务编排

### 5.1 ReAct (Reason-Act) 实现

```python
# src/orchestrator/react_loop.py
async def react_loop(user_input: str, context: EnvironmentContext):
    """
    ReAct 循环:LLM 根据上一步结果决定下一步动作
    """
    conversation_history = []
    max_iterations = 5  # 防止死循环

    for iteration in range(max_iterations):
        # 1. Reason: LLM 生成下一步指令
        prompt = build_prompt(
            user_input=user_input,
            context=context,
            history=conversation_history
        )
        llm_response = await llm_client.generate(prompt)
        instruction = parse_json(llm_response)

        # 2. Safety Check
        risk = check_safety(instruction)
        if risk in ["medium", "high"]:
            confirmed = await request_user_confirmation(instruction, risk)
            if not confirmed:
                return "Operation cancelled by user"

        # 3. Act: 执行 Worker
        worker = get_worker(instruction["worker"])
        result = await worker.execute(
            action=instruction["action"],
            args=instruction["args"]
        )

        # 4. 记录历史
        conversation_history.append({
            "instruction": instruction,
            "result": result
        })

        # 5. 判断是否完成
        if result.get("task_completed"):
            return result["message"]

        # 否则进入下一轮循环,LLM 会根据 result 决定下一步
```

### 5.2 多步任务示例

```
用户输入: "空间不足,清理一下"

Iteration 1:
  LLM Reason: 先检查磁盘使用情况
  Action: {"worker": "system", "action": "check_disk_usage"}
  Result: /var/log 占用 90%

Iteration 2:
  LLM Reason: 找出 /var/log 的大文件
  Action: {"worker": "system", "action": "find_large_files", "args": {"path": "/var/log"}}
  Result: [syslog.1: 250MB, nginx/access.log: 180MB]

Iteration 3:
  LLM Reason: 建议删除这些文件
  Action: {"worker": "system", "action": "delete_files", "args": {"files": [...]}, "risk_level": "high"}
  [等待用户确认] → 用户点击 Yes
  Result: 删除成功,释放 430MB
  task_completed: True
```

---

## 六、配置管理与模型切换

### 6.1 配置文件结构

```json
// ~/.opsai/config.json
{
  "llm": {
    "base_url": "http://localhost:11434/v1",
    "model": "qwen2.5:7b",
    "api_key": "",
    "timeout": 30,
    "max_tokens": 2048
  },
  "safety": {
    "auto_approve_safe": true,
    "cli_max_risk": "safe",
    "tui_max_risk": "high"
  },
  "audit": {
    "log_path": "~/.opsai/audit.log",
    "max_log_size_mb": 100,
    "retain_days": 90
  }
}
```

### 6.2 首次运行与自动初始化

**渐进式配置策略:**
1. 如果 `~/.opsai/config.json` 不存在,自动创建默认配置(指向 Ollama 本地端点)
2. 尝试连接 `localhost:11434`,如果失败,显示友好错误提示:
   ```
   Error: Cannot connect to default LLM endpoint (Ollama).

   Please either:
   1. Install Ollama: curl -fsSL https://ollama.com/install.sh | sh
   2. Configure cloud provider: opsai config set-llm
   ```
3. 用户可通过 `opsai config set-llm` 交互式配置其他提供商

### 6.3 交互式配置命令

```bash
$ opsai config set-llm

Select LLM provider:
  1) Ollama (local, recommended)
  2) OpenAI
  3) Anthropic Claude
  4) Custom endpoint

Choice: 2

Enter OpenAI API key: sk-...
Enter model name [gpt-4o-mini]: gpt-4o

✓ Configuration saved to ~/.opsai/config.json
✓ Testing connection... OK
```

### 6.4 设计原则

- 提供合理默认值(本地 Ollama),但不隐藏配置能力
- 首次运行不强制配置,而是尝试默认端点 + 友好错误提示
- 支持完全自定义 `base_url`/`model`/`api_key` 三元组

---

## 七、项目结构与技术实现

### 7.1 目录结构

```
mainer-cli/
├── src/
│   ├── cli.py                 # Typer CLI 入口
│   ├── tui.py                 # Textual TUI 入口
│   ├── orchestrator/
│   │   ├── engine.py          # ReAct 循环核心
│   │   ├── safety.py          # 安全检查模块
│   │   └── prompt.py          # Prompt 模板管理
│   ├── workers/
│   │   ├── base.py            # Worker 抽象基类
│   │   ├── system.py          # SystemWorker
│   │   ├── container.py       # ContainerWorker
│   │   └── audit.py           # AuditWorker
│   ├── context/
│   │   └── environment.py     # 环境信息收集
│   ├── config/
│   │   └── manager.py         # 配置文件管理
│   └── llm/
│       └── client.py          # LiteLLM 封装
├── tests/
│   ├── test_orchestrator.py
│   ├── test_workers.py
│   └── test_safety.py
├── pyproject.toml             # uv 项目配置
├── docs/
│   └── plans/
│       └── 2024-02-04-opsai-terminal-assistant-design.md
└── README.md
```

### 7.2 核心依赖

```toml
[project]
name = "opsai"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
    "textual>=0.47.0",      # TUI 框架
    "typer>=0.9.0",         # CLI 框架
    "litellm>=1.0.0",       # LLM 统一接口
    "pydantic>=2.0.0",      # 数据验证
    "docker>=7.0.0",        # Docker SDK
    "rich>=13.0.0",         # 终端美化
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 7.3 打包与分发

```bash
# 使用 uv 管理依赖
uv sync

# 开发模式运行
uv run opsai "test command"
uv run opsai-tui

# 构建分发包
uv build

# 目标安装方式
pip install opsai
# 或
curl -fsSL https://opsai.dev/install.sh | sh
```

### 7.4 关键技术点

**异步 I/O 架构:**
```python
# LLM 流式输出与 Worker 执行并发处理
async def handle_request(user_input):
    async with asyncio.TaskGroup() as tg:
        llm_task = tg.create_task(stream_llm_response())
        ui_task = tg.create_task(update_tui_display())
```

**Worker 标准接口:**
```python
class BaseWorker(ABC):
    @abstractmethod
    async def execute(self, action: str, args: dict) -> dict:
        """所有 Worker 必须实现此方法"""
        pass

    def get_capabilities(self) -> list[str]:
        """返回支持的 action 列表,用于 Prompt 生成"""
        pass
```

**类型安全(严格禁止 any 类型):**
```python
# src/types.py
from typing import Literal
from pydantic import BaseModel

RiskLevel = Literal["safe", "medium", "high"]

class Instruction(BaseModel):
    worker: str
    action: str
    args: dict[str, str | int | bool | list | dict]  # 明确参数类型范围
    risk_level: RiskLevel

class WorkerResult(BaseModel):
    success: bool
    data: list | dict | None
    message: str
    task_completed: bool = False
```

---

## 八、核心设计决策总结

| 设计点 | 选择方案 | 理由 |
|--------|----------|------|
| 指令数据结构 | 扁平 JSON | 消除特殊情况,Worker 无需理解依赖关系 |
| 安全检查位置 | Orchestrator 集中式 | 易于审计,避免逻辑分散 |
| 环境上下文收集 | 启动时一次性 | 避免为假想场景增加复杂度 |
| 审计日志格式 | 追加式文本 | 符合 Unix 哲学,`grep`/`tail` 即可分析 |
| LLM 配置策略 | 渐进式(默认本地) | 有合理默认,不强制配置 |
| 多步任务编排 | ReAct 循环 | 自然实现,无需 DAG 复杂度 |
| 类型系统 | 严格(禁止 any) | 提高代码可维护性和安全性 |

---

## 九、下一步行动

### 9.1 MVP 功能范围

**Phase 1 (核心框架):**
- [ ] 实现 Orchestrator ReAct 循环
- [ ] 实现 SystemWorker(仅 `find_large_files`, `check_disk_usage`)
- [ ] 实现 CLI 模式(仅 safe 级别操作)
- [ ] 实现配置管理(auto-init + set-llm 命令)

**Phase 2 (安全与审计):**
- [ ] 实现安全检查模块(黑名单 + 风险分级)
- [ ] 实现 AuditWorker(追加式日志)
- [ ] 实现 TUI 模式基础框架

**Phase 3 (扩展功能):**
- [ ] 实现 ContainerWorker(docker 操作)
- [ ] 实现 TUI 高危操作确认对话框
- [ ] 添加流式 LLM 输出显示

### 9.2 技术债务与未来优化

- 考虑添加 Worker 插件系统(用户自定义 Worker)
- 考虑支持本地 SQLite 作为可选审计存储(保持文本日志为默认)
- 考虑添加 `--dry-run` 模式(仅生成指令,不执行)

---

**文档状态:** ✅ 已验证
**准备进入实现阶段:** 是
