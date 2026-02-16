# 修复端口号默认偏见问题

## 问题描述

**场景**：
- 用户说："nginx运行在8080端口"
- 后续说："重启nginx容器"
- 系统生成命令：`lsof -ti :80 | xargs kill -9` ❌

**错误**：系统使用了nginx的默认端口80，而非用户明确提到的8080端口。

## 根因分析

### 1. 不是权限问题
这不是 `sudo` 权限问题，而是 **LLM 的知识偏见**导致的：
- LLM知识库中记录 nginx 默认使用 80 端口
- 当上下文不够明确时，LLM会回退到使用默认值
- 其他服务也有类似问题：redis(6379)、postgres(5432)、mysql(3306) 等

### 2. 上下文传递不足
尽管 prompt.py 已有"保留端口上下文"的规则（Rule 4: REFERENCE RESOLUTION），但：
- 端口信息在对话历史中可能被淹没
- LLM在生成命令时优先使用内置知识而非上下文
- 缺少明确的"禁止使用默认端口"指令

### 3. 提示词不够强烈
原有的提示词规则虽然提到要保留端口信息，但：
- 没有**明确禁止**使用默认端口
- 没有在用户输入中**自动提取并强调**端口号
- 缺少常见服务默认端口的黑名单

## 解决方案

### 修改 1: 增强 REFERENCE RESOLUTION 规则

在 `src/orchestrator/prompt.py` 的 Rule 4 中增加：

```python
- ⚠️⚠️⚠️ CRITICAL: NEVER USE DEFAULT PORTS! (绝对禁止使用默认端口!!!):
  * When user mentions a service (nginx/redis/postgres/etc.), DO NOT assume its default port!
  * User: "重启nginx容器" + context shows nginx on 8080 → use port 8080 (NOT 80!)
  * User: "关闭redis服务" + context shows redis on 6380 → use port 6380 (NOT 6379!)
  * If port number is NOT explicitly mentioned:
    - Option 1: Search previous Output for port info
    - Option 2: Use process name instead: pkill nginx
    - Option 3: Ask user: "请明确指定要操作的端口号"
  * Common default ports you MUST NOT assume:
    nginx=80, redis=6379, postgres=5432, mysql=3306, mongodb=27017
```

### 修改 2: Worker Details 顶部醒目警告

在 `shell.execute_command` 部分增加：

```python
- ⚠️⚠️⚠️ NEVER USE DEFAULT PORTS IN COMMANDS! Extract ACTUAL port from user input or context!
  * User mentions "nginx on 8080" → use 8080 in commands (NOT default 80!)
  * If port unknown → use process name kill (pkill/killall) OR ask user for port number
```

### 修改 3: 自动端口提取与强调

在 `build_user_prompt()` 函数中增加端口号自动提取逻辑：

```python
# 多种模式匹配端口号
port_patterns = [
    r'(\d{1,5})\s*(?:端口|port)',  # 8080端口, 8080 port
    r'(?:端口|port)\s*(\d{1,5})',  # 端口8080, port 8080
    r':\s*(\d{1,5})',              # :8080
    r'(?:在|on)\s*(\d{1,5})',      # 在8080, on 8080
]

if port_mentions:
    parts.append("")
    parts.append(f"⚠️⚠️⚠️ CRITICAL PORT INFO EXTRACTED FROM USER INPUT: {', '.join(unique_ports)}")
    parts.append("You MUST use these EXACT port numbers in your commands!")
    parts.append("DO NOT use any default port numbers (80, 443, 6379, 3306, 5432, etc.)!")
```

**关键特性**：
- 支持多种中文/英文表达方式
- 在 prompt 末尾用醒目格式强调提取的端口号
- 明确禁止使用默认端口

## 测试验证

创建了专门的测试文件 `tests/test_port_context_preservation.py`，包含：

1. **端口提取测试**：验证各种输入格式都能正确提取端口号
   - "nginx运行在8080端口" → 8080 ✅
   - "重启8080端口的nginx" → 8080 ✅
   - "关闭port 8080" → 8080 ✅
   - "nginx在8080,redis在6380" → 8080, 6380 ✅

2. **默认端口警告测试**：验证系统提示中包含禁止默认端口的规则

3. **无端口输入测试**：验证没有端口号时不会误提取

4. **替代方案测试**：验证端口未知时提供的替代方案

**所有测试通过** ✅

## 预期效果

修复后，当用户说：
```
用户：nginx运行在8080端口
用户：重启nginx容器
```

系统将生成：
```bash
lsof -ti :8080 | xargs kill -9  ✅ (正确使用8080)
```

而不是：
```bash
lsof -ti :80 | xargs kill -9    ❌ (错误使用默认80)
```

## 适用场景

此修复适用于所有可能使用默认端口的服务：
- nginx (80/443)
- redis (6379)
- postgres (5432)
- mysql (3306)
- mongodb (27017)
- 其他任何有默认端口的服务

## 后续建议

### 1. 提升智能体通用性
- 不要在代码或提示词中硬编码服务名/端口号/密码
- 始终从用户输入或系统探测中获取实际值
- 对不确定的信息，优先询问用户而非假设

### 2. 增强上下文记忆
考虑实现结构化的上下文记忆系统：
```python
# 示例：记录服务→端口映射
context_memory = {
    "nginx": {"port": 8080, "last_mentioned": "2026-02-16 10:30"},
    "redis": {"port": 6380, "last_mentioned": "2026-02-16 10:25"},
}
```

### 3. 多轮对话验证
在生成命令前，LLM 可以主动确认：
```
系统检测到您之前提到 nginx 运行在 8080 端口，
现在要重启的是 8080 端口的 nginx 吗？
```

## 相关提交

- `5492ba0`: refactor(prompt): 消除写死的端口号/服务名/密码，提升运维智能体通用性
- `f486558`: fix(prompt): 指代解析保留端口上下文 + 强制端口级 kill
- `247314f`: fix(prompt): 端口检查强制两步验证 — lsof 无权限时 curl 兜底
