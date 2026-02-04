# 智能运维对象分析 - 实现计划

> 基于设计文档: `2026-02-04-intelligent-analyze-design.md`

## 实现总览

本计划按照设计文档的优先级分为 4 个阶段（P0-P3），每个阶段包含具体的实现任务。

---

## Phase 0: 上下文传递改进 (P0)

**目标**: 让命令输出完整传递给 LLM，解决后续分析缺乏信息的问题。

### Task 0.1: 扩展 WorkerResult.data 类型定义

**文件**: `src/types.py`

**变更内容**:
```python
# 当前类型
data: Union[list[dict[str, Union[str, int]]], dict[str, Union[str, int]], None]

# 扩展为支持 raw_output
data: Union[
    list[dict[str, Union[str, int]]],
    dict[str, Union[str, int, bool]],  # 添加 bool 支持 truncated 标记
    None
]
```

**注意**: 设计文档提到可能需要新增 `AnalyzeTarget` 类型，在 Phase 1 实现。

### Task 0.2: 修改 ShellWorker 返回 raw_output

**文件**: `src/workers/shell.py`

**变更内容**:
1. 在 `execute` 方法中，将完整命令输出存入 `data.raw_output`
2. 实现输出截断逻辑（超过 4000 字符时保留头尾各 2000 字符）
3. 添加 `truncated` 标记表示输出是否被截断

**代码示例**:
```python
MAX_OUTPUT_LENGTH = 4000
TRUNCATE_HEAD = 2000
TRUNCATE_TAIL = 2000

def _truncate_output(self, output: str) -> tuple[str, bool]:
    """截断过长输出，返回 (截断后输出, 是否截断)"""
    if len(output) <= MAX_OUTPUT_LENGTH:
        return output, False
    
    head = output[:TRUNCATE_HEAD]
    tail = output[-TRUNCATE_TAIL:]
    return f"{head}\n\n... [truncated {len(output) - MAX_OUTPUT_LENGTH} characters] ...\n\n{tail}", True
```

**更新 data 返回值**:
```python
raw_output, truncated = self._truncate_output(stdout)
return WorkerResult(
    success=success,
    data={
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "raw_output": raw_output,  # 新增
        "truncated": truncated,     # 新增
    },
    message="\n".join(message_parts),
    task_completed=success,
)
```

### Task 0.3: 修改 PromptBuilder 包含完整输出

**文件**: `src/orchestrator/prompt.py`

**变更内容**:
在 `build_user_prompt` 方法中添加 raw_output 到历史记录：

```python
def build_user_prompt(
    self,
    user_input: str,
    history: Optional[list[ConversationEntry]] = None,
) -> str:
    parts = []

    if history:
        parts.append("Previous actions:")
        for entry in history:
            parts.append(
                f"- Action: {entry.instruction.worker}.{entry.instruction.action}"
            )
            parts.append(f"  Result: {entry.result.message}")
            # 新增：传递完整输出（如果存在）
            if entry.result.data and isinstance(entry.result.data, dict):
                raw_output = entry.result.data.get("raw_output", "")
                if raw_output:
                    truncated = entry.result.data.get("truncated", False)
                    truncate_note = " [OUTPUT TRUNCATED]" if truncated else ""
                    parts.append(f"  Output{truncate_note}:\n```\n{raw_output}\n```")
        parts.append("")

    parts.append(f"User request: {user_input}")
    return "\n".join(parts)
```

### Task 0.4: 添加单元测试

**文件**: `tests/test_workers_shell.py`（补充）

**测试用例**:
1. `test_shell_returns_raw_output` - 验证返回值包含 raw_output
2. `test_shell_truncates_long_output` - 验证超长输出被截断
3. `test_shell_truncate_preserves_head_tail` - 验证截断保留头尾内容

**文件**: `tests/test_prompt.py`（补充）

**测试用例**:
1. `test_build_user_prompt_with_raw_output` - 验证 prompt 包含完整输出
2. `test_build_user_prompt_with_truncated_output` - 验证截断标记显示

---

## Phase 1: AnalyzeWorker 基础实现 (P1)

**目标**: 实现 AnalyzeWorker，支持 Docker 容器分析。

### Task 1.1: 新增 AnalyzeTarget 类型

**文件**: `src/types.py`

**新增内容**:
```python
AnalyzeTargetType = Literal[
    "docker",      # Docker 容器
    "process",     # 进程
    "port",        # 端口
    "file",        # 文件
    "systemd",     # Systemd 服务
    "network",     # 网络连接
]

class AnalyzeTarget(BaseModel):
    """分析对象"""
    type: AnalyzeTargetType = Field(..., description="对象类型")
    name: str = Field(..., description="对象标识符（容器名、PID、端口号等）")
    context: Optional[str] = Field(default=None, description="额外上下文信息")
```

### Task 1.2: 实现 AnalyzeWorker

**文件**: `src/workers/analyze.py`（新建）

**类结构**:
```python
class AnalyzeWorker(BaseWorker):
    """智能分析 Worker
    
    支持的操作:
    - explain: 分析并解释运维对象
    """
    
    def __init__(self, llm_client: LLMClient) -> None:
        """初始化，需要 LLM 客户端用于生成分析步骤和总结"""
        self._llm_client = llm_client
        self._cache = AnalyzeTemplateCache()  # Phase 2 实现
    
    @property
    def name(self) -> str:
        return "analyze"
    
    def get_capabilities(self) -> list[str]:
        return ["explain"]
    
    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行分析操作"""
        if action != "explain":
            return WorkerResult(success=False, message=f"Unknown action: {action}")
        
        target_type = args.get("type", "")
        target_name = args.get("target", "")
        
        # 1. 获取分析步骤（命令列表）
        commands = await self._get_analyze_commands(target_type, target_name)
        
        # 2. 执行命令收集信息
        collected_info = await self._collect_info(commands, target_name)
        
        # 3. 调用 LLM 总结分析
        summary = await self._generate_summary(target_type, target_name, collected_info)
        
        return WorkerResult(
            success=True,
            message=summary,
            task_completed=True,
        )
```

**核心方法**:

```python
async def _get_analyze_commands(
    self, 
    target_type: str, 
    target_name: str
) -> list[str]:
    """获取分析命令列表
    
    优先从缓存获取，无缓存则调用 LLM 生成
    """
    # Phase 2 实现缓存逻辑
    # 目前直接调用 LLM
    return await self._generate_commands_via_llm(target_type, target_name)

async def _generate_commands_via_llm(
    self,
    target_type: str,
    target_name: str,
) -> list[str]:
    """调用 LLM 生成分析步骤"""
    prompt = f"""Generate shell commands to analyze a {target_type} named "{target_name}".

Return ONLY a JSON array of command strings, no explanation.
Commands should be safe (read-only) and gather useful diagnostic info.

Example for docker:
["docker inspect compoder-mongo", "docker logs --tail 50 compoder-mongo"]

Example for process:
["ps aux | grep 1234", "lsof -p 1234"]

Your response (JSON array only):"""
    
    response = await self._llm_client.generate("You are a Linux expert.", prompt)
    # 解析 JSON 数组
    return self._parse_command_list(response)

async def _collect_info(
    self,
    commands: list[str],
    target_name: str,
) -> dict[str, str]:
    """执行命令收集信息"""
    shell_worker = ShellWorker()
    results: dict[str, str] = {}
    
    for cmd in commands:
        # 替换占位符
        actual_cmd = cmd.replace("{name}", target_name)
        result = await shell_worker.execute("execute_command", {"command": actual_cmd})
        
        if result.success and result.data:
            raw_output = result.data.get("raw_output", result.message)
            results[actual_cmd] = str(raw_output)
        else:
            results[actual_cmd] = f"[Failed: {result.message}]"
    
    return results

async def _generate_summary(
    self,
    target_type: str,
    target_name: str,
    collected_info: dict[str, str],
) -> str:
    """调用 LLM 生成分析总结"""
    info_text = "\n\n".join([
        f"=== {cmd} ===\n{output}"
        for cmd, output in collected_info.items()
    ])
    
    prompt = f"""Analyze this {target_type} "{target_name}" based on the following information:

{info_text}

Provide a concise Chinese summary explaining:
1. What this {target_type} is and its purpose
2. Key configuration details (ports, volumes, environment, etc.)
3. Current status and any notable observations

Keep the summary under 200 words. Use natural language, not bullet points."""
    
    return await self._llm_client.generate(
        "You are an expert ops engineer. Provide clear, actionable analysis.",
        prompt
    )
```

### Task 1.3: 更新 Prompt 添加分析意图识别

**文件**: `src/orchestrator/prompt.py`

**修改 WORKER_CAPABILITIES**:
```python
WORKER_CAPABILITIES: dict[str, list[str]] = {
    "chat": ["respond"],
    "shell": ["execute_command"],
    "system": ["list_files", "find_large_files", "check_disk_usage", "delete_files"],
    "container": ["list_containers", "restart_container", "view_logs"],
    "audit": ["log_operation"],
    "analyze": ["explain"],  # 新增
}
```

**修改 build_system_prompt 添加分析规则**:
```python
# 在 Worker Details 部分添加：
- analyze.explain: Analyze and explain ops objects (containers, processes, ports, etc.)
  - args: {{"target": "object_name", "type": "docker|process|port|file|systemd"}}
  - Use when user asks "这是干嘛的", "有什么用", "是什么", "explain", "what is"
  - Example: {{"worker": "analyze", "action": "explain", "args": {{"target": "compoder-mongo", "type": "docker"}}, "risk_level": "safe", "task_completed": false}}

# 在 CRITICAL Rules 部分添加：
7. For analysis questions (含"是干嘛的"、"有什么用"、"是什么"、"解释"、"分析"):
   - Use analyze.explain with target name and type
   - The analyze worker will gather info and provide summary automatically
```

### Task 1.4: 注册 AnalyzeWorker

**文件**: `src/orchestrator/engine.py`

**修改内容**:
```python
# 在 __init__ 中添加：
# 注册 AnalyzeWorker
try:
    from src.workers.analyze import AnalyzeWorker
    self._workers["analyze"] = AnalyzeWorker(self._llm_client)
except ImportError:
    pass
```

### Task 1.5: 添加单元测试

**文件**: `tests/test_analyze_worker.py`（新建）

**测试用例**:
1. `test_analyze_worker_name` - 验证 worker 名称
2. `test_analyze_worker_capabilities` - 验证能力列表
3. `test_analyze_explain_docker` - 模拟 Docker 分析流程
4. `test_analyze_command_failure_handled` - 验证命令失败时的优雅降级
5. `test_analyze_unknown_action` - 验证未知 action 返回错误

---

## Phase 2: 缓存机制 (P2)

**目标**: 实现分析模板缓存，避免重复调用 LLM 生成分析步骤。

### Task 2.1: 实现缓存管理模块

**文件**: `src/workers/cache.py`（新建）

**类结构**:
```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class AnalyzeTemplate(BaseModel):
    """分析模板"""
    commands: list[str] = Field(..., description="命令列表，支持 {name} 占位符")
    created_at: str = Field(..., description="创建时间 ISO 格式")
    hit_count: int = Field(default=0, description="命中次数")


class AnalyzeTemplateCache:
    """分析模板缓存管理器
    
    存储位置: ~/.opsai/cache/analyze_templates.json
    """
    
    DEFAULT_CACHE_PATH = Path.home() / ".opsai" / "cache" / "analyze_templates.json"
    
    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self._cache_path = cache_path or self.DEFAULT_CACHE_PATH
        self._templates: dict[str, AnalyzeTemplate] = {}
        self._load()
    
    def _load(self) -> None:
        """加载缓存文件"""
        if self._cache_path.exists():
            try:
                with self._cache_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        self._templates[key] = AnalyzeTemplate(**value)
            except (json.JSONDecodeError, Exception):
                # 缓存损坏时忽略，不阻塞主流程
                self._templates = {}
    
    def _save(self) -> None:
        """保存缓存文件"""
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_path.open("w", encoding="utf-8") as f:
            data = {k: v.model_dump() for k, v in self._templates.items()}
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get(self, target_type: str) -> Optional[list[str]]:
        """获取分析模板
        
        Args:
            target_type: 对象类型（docker, process, port 等）
            
        Returns:
            命令列表，不存在返回 None
        """
        template = self._templates.get(target_type)
        if template:
            template.hit_count += 1
            self._save()
            return template.commands
        return None
    
    def set(self, target_type: str, commands: list[str]) -> None:
        """设置分析模板
        
        Args:
            target_type: 对象类型
            commands: 命令列表
        """
        self._templates[target_type] = AnalyzeTemplate(
            commands=commands,
            created_at=datetime.now().isoformat(),
            hit_count=0,
        )
        self._save()
    
    def clear(self, target_type: Optional[str] = None) -> None:
        """清除缓存
        
        Args:
            target_type: 指定类型，None 表示清除全部
        """
        if target_type:
            self._templates.pop(target_type, None)
        else:
            self._templates = {}
        self._save()
    
    def list_all(self) -> dict[str, AnalyzeTemplate]:
        """列出所有缓存模板"""
        return self._templates.copy()
```

### Task 2.2: 集成缓存到 AnalyzeWorker

**文件**: `src/workers/analyze.py`

**修改 _get_analyze_commands 方法**:
```python
async def _get_analyze_commands(
    self, 
    target_type: str, 
    target_name: str
) -> list[str]:
    """获取分析命令列表，优先使用缓存"""
    # 尝试从缓存获取
    cached = self._cache.get(target_type)
    if cached:
        return cached
    
    # 缓存未命中，调用 LLM 生成
    commands = await self._generate_commands_via_llm(target_type, target_name)
    
    # 存入缓存供下次使用
    if commands:
        self._cache.set(target_type, commands)
    
    return commands
```

### Task 2.3: 添加 CLI 缓存管理命令

**文件**: `src/cli/main.py`（假设存在）

**新增命令**:
```python
@app.command()
def cache(
    action: str = typer.Argument(..., help="操作：list, clear"),
    target_type: Optional[str] = typer.Option(None, "--type", "-t", help="对象类型"),
):
    """管理分析模板缓存"""
    from src.workers.cache import AnalyzeTemplateCache
    
    cache = AnalyzeTemplateCache()
    
    if action == "list":
        templates = cache.list_all()
        if not templates:
            console.print("[dim]No cached templates[/dim]")
            return
        for name, template in templates.items():
            console.print(f"[bold]{name}[/bold] (hits: {template.hit_count})")
            for cmd in template.commands:
                console.print(f"  - {cmd}")
    
    elif action == "clear":
        cache.clear(target_type)
        if target_type:
            console.print(f"Cleared cache for: {target_type}")
        else:
            console.print("Cleared all cache")
```

### Task 2.4: 添加单元测试

**文件**: `tests/test_cache.py`（新建）

**测试用例**:
1. `test_cache_get_nonexistent` - 获取不存在的缓存返回 None
2. `test_cache_set_and_get` - 设置并获取缓存
3. `test_cache_hit_count_increment` - 验证命中计数递增
4. `test_cache_clear_specific` - 清除指定类型缓存
5. `test_cache_clear_all` - 清除所有缓存
6. `test_cache_persistence` - 验证缓存持久化到文件
7. `test_cache_corrupted_file_handled` - 验证损坏文件不阻塞

---

## Phase 3: 扩展对象类型 (P3)

**目标**: 扩展 AnalyzeWorker 支持更多运维对象类型。

### Task 3.1: 预置常用对象类型的默认命令

**文件**: `src/workers/analyze.py`

**新增默认模板**:
```python
DEFAULT_ANALYZE_COMMANDS: dict[str, list[str]] = {
    "docker": [
        "docker inspect {name}",
        "docker logs --tail 50 {name}",
    ],
    "process": [
        "ps aux | grep {name}",
        "lsof -p {name} 2>/dev/null | head -50",
        "cat /proc/{name}/cmdline 2>/dev/null | tr '\\0' ' '",
    ],
    "port": [
        "lsof -i :{name}",
        "ss -tlnp | grep :{name}",
        "netstat -tlnp 2>/dev/null | grep :{name}",
    ],
    "file": [
        "file {name}",
        "ls -la {name}",
        "stat {name}",
        "head -20 {name} 2>/dev/null",
    ],
    "systemd": [
        "systemctl status {name}",
        "journalctl -u {name} --no-pager -n 30",
        "systemctl cat {name}",
    ],
    "network": [
        "ss -tlnp | grep {name}",
        "netstat -an | grep {name}",
        "ip addr show {name} 2>/dev/null",
    ],
}
```

**修改 _get_analyze_commands**:
```python
async def _get_analyze_commands(
    self, 
    target_type: str, 
    target_name: str
) -> list[str]:
    """获取分析命令列表
    
    优先级：缓存 > 预置默认 > LLM 生成
    """
    # 1. 尝试从缓存获取
    cached = self._cache.get(target_type)
    if cached:
        return cached
    
    # 2. 使用预置默认命令
    if target_type in DEFAULT_ANALYZE_COMMANDS:
        return DEFAULT_ANALYZE_COMMANDS[target_type]
    
    # 3. 未知类型，调用 LLM 生成
    commands = await self._generate_commands_via_llm(target_type, target_name)
    
    # 存入缓存供下次使用
    if commands:
        self._cache.set(target_type, commands)
    
    return commands
```

### Task 3.2: 添加对象类型自动检测

**文件**: `src/workers/analyze.py`

**新增方法**:
```python
def _detect_target_type(self, target_name: str) -> str:
    """根据目标名称猜测对象类型
    
    用于用户未明确指定类型时的 fallback
    """
    # 纯数字 - 可能是 PID 或端口
    if target_name.isdigit():
        port = int(target_name)
        if 1 <= port <= 65535:
            return "port"  # 先假设是端口
        return "process"  # 假设是 PID
    
    # 以 / 开头 - 文件路径
    if target_name.startswith("/"):
        return "file"
    
    # .service 结尾 - systemd
    if target_name.endswith(".service"):
        return "systemd"
    
    # 默认假设 docker 容器
    return "docker"
```

### Task 3.3: 增强错误处理 - 对象类型识别失败

**文件**: `src/workers/analyze.py`

**处理逻辑**:
```python
async def execute(
    self,
    action: str,
    args: dict[str, ArgValue],
) -> WorkerResult:
    """执行分析操作"""
    if action != "explain":
        return WorkerResult(success=False, message=f"Unknown action: {action}")
    
    target = args.get("target", "")
    target_type = args.get("type", "")
    
    # 目标为空时，请求澄清
    if not target:
        return WorkerResult(
            success=False,
            message="你想分析哪个对象？请指定目标名称（如容器名、进程 PID、端口号等）",
            task_completed=False,
        )
    
    # 类型为空时，尝试自动检测
    if not target_type:
        target_type = self._detect_target_type(str(target))
    
    # ... 继续正常分析流程
```

### Task 3.4: 添加集成测试

**文件**: `tests/test_analyze_integration.py`（新建）

**测试用例**:
1. `test_analyze_docker_end_to_end` - Docker 容器完整分析流程
2. `test_analyze_process_by_pid` - 进程分析
3. `test_analyze_port_listening` - 端口分析
4. `test_analyze_file` - 文件分析
5. `test_analyze_auto_detect_type` - 类型自动检测
6. `test_analyze_missing_target_prompts_clarification` - 缺少目标时提示澄清

---

## 实现顺序与依赖关系

```
Phase 0 (P0) ──────────────────────────────────────────────────
    │
    ├── Task 0.1: 扩展 WorkerResult.data 类型
    │       ↓
    ├── Task 0.2: ShellWorker 返回 raw_output ←─────┐
    │       ↓                                       │
    ├── Task 0.3: PromptBuilder 包含完整输出 ←──────┤
    │       ↓                                       │
    └── Task 0.4: 单元测试 ─────────────────────────┘

Phase 1 (P1) ──────────────────────────────────────────────────
    │   (依赖 Phase 0 完成)
    │
    ├── Task 1.1: 新增 AnalyzeTarget 类型
    │       ↓
    ├── Task 1.2: 实现 AnalyzeWorker
    │       ↓
    ├── Task 1.3: 更新 Prompt 分析意图识别
    │       ↓
    ├── Task 1.4: 注册 AnalyzeWorker
    │       ↓
    └── Task 1.5: 单元测试

Phase 2 (P2) ──────────────────────────────────────────────────
    │   (依赖 Phase 1 完成)
    │
    ├── Task 2.1: 实现缓存管理模块
    │       ↓
    ├── Task 2.2: 集成缓存到 AnalyzeWorker
    │       ↓
    ├── Task 2.3: CLI 缓存管理命令
    │       ↓
    └── Task 2.4: 单元测试

Phase 3 (P3) ──────────────────────────────────────────────────
    │   (依赖 Phase 2 完成)
    │
    ├── Task 3.1: 预置默认命令模板
    │       ↓
    ├── Task 3.2: 对象类型自动检测
    │       ↓
    ├── Task 3.3: 增强错误处理
    │       ↓
    └── Task 3.4: 集成测试
```

---

## 文件变更汇总

| 文件 | Phase | 变更类型 | 说明 |
|------|-------|----------|------|
| `src/types.py` | P0, P1 | 修改 | 扩展 data 类型、新增 AnalyzeTarget |
| `src/workers/shell.py` | P0 | 修改 | 返回 raw_output、截断逻辑 |
| `src/orchestrator/prompt.py` | P0, P1 | 修改 | 传递完整输出、分析意图识别 |
| `src/workers/analyze.py` | P1, P2, P3 | 新建 | AnalyzeWorker 核心实现 |
| `src/workers/cache.py` | P2 | 新建 | 分析模板缓存管理 |
| `src/orchestrator/engine.py` | P1 | 修改 | 注册 AnalyzeWorker |
| `src/cli/main.py` | P2 | 修改 | 添加 cache 命令 |
| `tests/test_workers_shell.py` | P0 | 修改 | 补充测试 |
| `tests/test_prompt.py` | P0 | 修改 | 补充测试 |
| `tests/test_analyze_worker.py` | P1 | 新建 | AnalyzeWorker 单元测试 |
| `tests/test_cache.py` | P2 | 新建 | 缓存模块测试 |
| `tests/test_analyze_integration.py` | P3 | 新建 | 集成测试 |

---

## 验收标准

### Phase 0 完成标准
- [x] `ShellWorker.execute` 返回的 `data` 包含 `raw_output` 字段
- [x] 超过 4000 字符的输出被正确截断
- [x] `PromptBuilder.build_user_prompt` 输出包含历史命令的完整输出
- [x] 所有新增测试通过

### Phase 1 完成标准
- [x] 用户询问"这个 docker 是干嘛的"时，系统自动执行 `docker inspect` 和 `docker logs`
- [x] LLM 返回人类可读的中文分析总结
- [x] `analyze.explain` 出现在 Worker 能力列表中
- [x] 所有新增测试通过

### Phase 2 完成标准
- [x] 首次分析 Docker 容器后，缓存文件被创建
- [x] 再次分析 Docker 容器时，命中缓存而非调用 LLM
- [x] `opsai cache list` 显示缓存内容
- [x] `opsai cache clear` 清除缓存
- [x] 所有新增测试通过

### Phase 3 完成标准
- [x] 支持分析 process、port、file、systemd 等对象类型
- [x] 用户输入数字时自动检测为端口或 PID
- [x] 用户输入路径时自动检测为文件
- [x] 目标为空时提示用户澄清
- [x] 所有新增测试通过

---

## 实现完成日期: 2026-02-04
