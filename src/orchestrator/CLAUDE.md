[根目录](../../CLAUDE.md) > [src](../) > **orchestrator**

# orchestrator 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

ReAct 引擎核心模块，负责 LLM 推理决策、安全策略执行和 LangGraph 状态图编排。是 Orchestrator-Workers 架构中"大脑"部分。

## 入口与启动

- **`engine.py`** -- `OrchestratorEngine` 类，统一入口。初始化所有 Workers、LLMClient、ReactGraph。提供 `react_loop_graph()`（主循环）、`resume_react_loop()`（中断恢复）、`execute_instruction()`（单步执行）。
- **`graph/react_graph.py`** -- `ReactGraph` 类，LangGraph 状态图封装，定义节点路由：`preprocess -> reason -> safety -> [approve?] -> execute -> check -> [loop/end]`。

## 对外接口

| 方法 | 说明 |
|------|------|
| `OrchestratorEngine.react_loop_graph(user_input, max_iterations, session_id, session_history)` | 执行完整 ReAct 循环 |
| `OrchestratorEngine.resume_react_loop(session_id, approval_granted)` | 审批后恢复中断的循环 |
| `OrchestratorEngine.execute_instruction(instruction)` | 单步执行一条指令 |
| `OrchestratorEngine.get_graph_state(session_id)` | 获取 LangGraph 会话状态 |
| `check_safety(instruction)` -> `RiskLevel` | 安全检查（向后兼容，委托给 PolicyEngine） |
| `PromptBuilder.build_system_prompt(context, workers, user_input)` | 构建系统 Prompt |
| `PromptBuilder.build_tool_descriptions(workers)` | 从 Worker 元数据动态生成工具描述 |

## 关键依赖与配置

- 依赖: `langgraph`, `src.llm.client.LLMClient`, `src.workers.base.BaseWorker`, `src.context.environment.EnvironmentContext`
- 配置项: `OpsAIConfig.safety`（风险等级控制）、`OpsAIConfig.llm`（模型参数）

## 数据模型

- **`ReactState`** (`graph/react_state.py`): LangGraph TypedDict 状态，包含 user_input, messages, iteration, current_instruction, risk_level, needs_approval, task_completed, final_message 等字段。
- **`ReasonResult`** (`reason_strategies.py`): 策略执行结果，包含 instruction, thinking, is_final, is_error。
- **`ReasonContext`** (`reason_strategies.py`): 策略共享上下文，避免每个策略持有全部依赖。

## 子模块结构

```
orchestrator/
  __init__.py
  engine.py              # OrchestratorEngine 主引擎
  prompt.py              # PromptBuilder + 工具描述动态生成
  safety.py              # 向后兼容层，委托给 PolicyEngine
  policy_engine.py       # 统一安全策略引擎（白名单 + 规则引擎）
  command_whitelist.py   # Shell 命令白名单校验
  whitelist_rules.py     # 白名单规则定义
  risk_analyzer.py       # 命令风险分析
  preprocessor.py        # 请求预处理器（意图识别、指代消解）
  reason_strategies.py   # 策略模式 reason_node 实现
  validation.py          # 指令验证
  instruction.py         # 指令解析
  scenarios.py           # 场景推荐系统
  error_helper.py        # 错误恢复辅助
  graph_adapter.py       # LangGraph 消息格式转换
  graph/
    __init__.py
    react_graph.py       # LangGraph 状态图定义
    react_nodes.py       # 节点实现（委托给策略模块）
    react_state.py       # ReactState TypedDict
    checkpoint.py        # 检查点持久化
```

## 测试与质量

相关测试文件:
- `tests/test_engine.py` -- 引擎集成测试
- `tests/test_prompt.py` -- Prompt 构建测试
- `tests/test_safety.py` -- 安全检查测试
- `tests/test_risk_analyzer.py` -- 风险分析测试
- `tests/test_command_whitelist.py` -- 白名单测试
- `tests/test_policy_engine.py` -- 策略引擎测试
- `tests/test_preprocessor_identity.py` -- 预处理器测试
- `tests/test_scenarios.py` -- 场景推荐测试
- `tests/test_error_helper.py` -- 错误辅助测试
- `tests/test_react_graph.py` -- LangGraph 状态图测试

## 常见问题 (FAQ)

**Q: reason_node 的推理逻辑在哪里?**
A: 通过策略模式委托给 `reason_strategies.py`，`react_nodes.py` 只做节点调度。

**Q: 安全检查的入口在哪?**
A: `safety.py` 的 `check_safety()` 是向后兼容层，实际逻辑在 `policy_engine.py` 的 `PolicyEngine.check_instruction()`。

**Q: Prompt 中的工具描述是硬编码的吗?**
A: 不是。`PromptBuilder.build_tool_descriptions()` 从 Worker 的 `description` + `get_actions()` 动态生成。`WORKER_CAPABILITIES` 只是无 Worker 实例时的 fallback。

## 相关文件清单

- `src/orchestrator/engine.py`
- `src/orchestrator/prompt.py`
- `src/orchestrator/safety.py`
- `src/orchestrator/policy_engine.py`
- `src/orchestrator/command_whitelist.py`
- `src/orchestrator/whitelist_rules.py`
- `src/orchestrator/risk_analyzer.py`
- `src/orchestrator/preprocessor.py`
- `src/orchestrator/reason_strategies.py`
- `src/orchestrator/validation.py`
- `src/orchestrator/instruction.py`
- `src/orchestrator/scenarios.py`
- `src/orchestrator/error_helper.py`
- `src/orchestrator/graph_adapter.py`
- `src/orchestrator/graph/react_graph.py`
- `src/orchestrator/graph/react_nodes.py`
- `src/orchestrator/graph/react_state.py`
- `src/orchestrator/graph/checkpoint.py`
