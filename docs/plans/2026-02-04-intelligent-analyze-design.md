# 智能运维对象分析设计

## 概述

当用户问"这个 docker 服务是干嘛的"类问题时，系统应该：
1. **识别分析意图** - 区分"列表查询"和"分析理解"
2. **收集上下文** - 自动执行多个命令收集信息
3. **智能总结** - 用 LLM 生成人类可读的分析

## 问题背景

当前系统存在两个问题：

1. **模型能力有限** - 小模型（如 qwen2.5:7b）无法可靠地执行复杂的多步推理
2. **上下文传递不完整** - 命令输出没有完整传递给 LLM，导致后续分析缺乏信息

### 当前行为（错误）

```
用户: 我有哪些 docker 服务
系统: docker ps → 显示容器列表

用户: 这个 docker 服务是干嘛的
系统: docker ps → 再次显示容器列表（没有分析）
```

### 期望行为（正确）

```
用户: 我有哪些 docker 服务
系统: docker ps → 显示容器列表

用户: 这个 docker 服务是干嘛的
系统:
  1. docker inspect compoder-mongo
  2. docker logs --tail 20 compoder-mongo
  3. 分析总结: "这是一个 MongoDB 5.0.18 数据库服务，通过 27017 端口提供数据库连接服务..."
```

## 设计决策

- **覆盖范围**: 通用运维对象（Docker、进程、端口、文件、服务、网络连接等）
- **策略**: 混合策略 - Prompt 增强 + 分析 Worker 兜底
- **模板组织**: LLM 动态生成 + 缓存复用

## 架构变更

### 新增 AnalyzeWorker

文件: `src/workers/analyze.py`

职责：
- 接收"分析对象"请求（如容器名、端口号、进程 PID）
- 调用 LLM 生成分析步骤（需要执行哪些命令）
- 执行命令收集信息
- 调用 LLM 总结分析结果

```
用户: "这个 docker 服务是干嘛的"
         ↓
Orchestrator 识别为分析意图
         ↓
生成 Instruction: {worker: "analyze", action: "explain", args: {target: "compoder-mongo", type: "docker"}}
         ↓
AnalyzeWorker:
  1. 查缓存：是否有 docker 类型的分析模板？
  2. 无缓存 → 调用 LLM 生成分析步骤
     LLM 返回: ["docker inspect {name}", "docker logs --tail 20 {name}"]
  3. 执行命令，收集输出
  4. 调用 LLM 分析总结
  5. 缓存分析模板供下次复用
         ↓
返回: "这是一个 MongoDB 5.0.18 数据库服务，通过 27017 端口对外提供服务..."
```

### Prompt 增强

在 `prompt.py` 中添加分析意图识别规则：
- 关键词触发：`"是干嘛的"`, `"有什么用"`, `"是什么"`, `"explain"`, `"what is"` 等
- 指导 LLM 在这些场景使用 `analyze.explain`

## 上下文传递改进

### 问题

当前 `build_user_prompt` 只传递了 action 名称和 message，没有传递命令的完整输出。

```python
# 当前实现 (prompt.py:121-124)
parts.append(f"- Action: {entry.instruction.worker}.{entry.instruction.action}")
parts.append(f"  Result: {entry.result.message}")
```

### 改进

在 `WorkerResult` 中保留原始输出，传递给 LLM 用于分析。

```python
# 改进后
parts.append(f"- Action: {entry.instruction.worker}.{entry.instruction.action}")
parts.append(f"  Result: {entry.result.message}")
if entry.result.data:  # 完整输出
    parts.append(f"  Output:\n{entry.result.data.get('raw_output', '')}")
```

### 影响范围

- `ShellWorker.execute_command` - 返回时将命令输出存入 `data.raw_output`
- `PromptBuilder.build_user_prompt` - 构建 prompt 时包含完整输出
- 需要考虑输出截断（避免超长输出撑爆上下文）

## 缓存机制设计

### 缓存内容

分析步骤模板（LLM 生成的命令列表）

### 缓存键

对象类型（docker、process、port、file、systemd 等）

### 存储位置

`~/.opsai/cache/analyze_templates.json`

```json
{
  "docker": {
    "commands": [
      "docker inspect {name}",
      "docker logs --tail 20 {name}"
    ],
    "created_at": "2026-02-04T10:00:00Z",
    "hit_count": 15
  },
  "port": {
    "commands": [
      "lsof -i :{port}",
      "ss -tlnp | grep :{port}"
    ],
    "created_at": "2026-02-04T11:00:00Z",
    "hit_count": 3
  }
}
```

### 缓存策略

- 首次分析某类型对象时生成，永久有效
- 用户可通过 `opsai cache clear` 手动清除
- 不设过期时间（分析步骤相对稳定，除非系统环境大变）

### Fallback

缓存读取失败时，直接调用 LLM 生成，不阻塞主流程

## 错误处理与边界情况

### 1. 对象类型识别失败

用户说"这是干嘛的"，但上下文不清楚"这"是什么：
- 策略：LLM 生成一个澄清问题，通过 `chat.respond` 询问用户
- 示例：`"你想了解哪个对象？是刚才列出的 docker 容器，还是其他东西？"`

### 2. 命令执行失败

分析步骤中某个命令失败（如容器已停止、权限不足）：
- 策略：跳过失败命令，用已收集的信息进行分析
- 在结果中标注：`"注意：部分信息无法获取（容器日志不可用）"`

### 3. LLM 生成的分析步骤不合理

LLM 可能生成危险命令或无效命令：
- 策略：复用现有 `check_safety` 机制，高危命令需用户确认
- 分析步骤中的命令默认限制为 `safe` 级别

### 4. 输出过长

某些命令输出巨大（如 `docker inspect` 完整输出）：
- 策略：截断到 4000 字符，保留头尾各 2000 字符
- 让 LLM 在分析时知道输出被截断

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/workers/analyze.py` | 新增 | AnalyzeWorker 实现 |
| `src/workers/cache.py` | 新增 | 分析模板缓存管理 |
| `src/orchestrator/prompt.py` | 修改 | 添加分析意图识别规则、增强上下文传递 |
| `src/orchestrator/engine.py` | 修改 | 注册 AnalyzeWorker |
| `src/workers/shell.py` | 修改 | 返回值包含 `raw_output` |
| `src/types.py` | 修改 | 可能需要新增 `AnalyzeTarget` 类型 |
| `tests/test_analyze_worker.py` | 新增 | AnalyzeWorker 单元测试 |

## 实现优先级

1. **P0 - 上下文传递改进**: 修改 ShellWorker 和 PromptBuilder，让命令输出完整传递
2. **P1 - AnalyzeWorker 基础实现**: 支持 Docker 容器分析
3. **P2 - 缓存机制**: 实现分析模板缓存
4. **P3 - 扩展对象类型**: 支持进程、端口、文件等
