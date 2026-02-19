[根目录](../../CLAUDE.md) > [src](../) > **llm**

# llm 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

封装 OpenAI SDK，提供统一的 LLM 调用接口。支持文本模式（JSON 解析）和 Function Calling 模式（原生工具调用）。管理模型预设配置。

## 入口与启动

- **`client.py`** -- `LLMClient` 类，统一 LLM 调用入口。
- **`presets.py`** -- 模型预设定义（local-qwen, openai-gpt4o, deepseek 等）。

## 对外接口

| 方法 | 说明 |
|------|------|
| `LLMClient.generate(system_prompt, user_prompt, history)` | 文本模式生成（返回原始字符串） |
| `LLMClient.generate_with_tools(system_prompt, user_prompt, workers, history)` | Function Calling 模式（返回 `ToolCallResult`） |
| `LLMClient.build_messages(system_prompt, user_prompt, history)` | 构建消息列表 |
| `LLMClient.parse_json_response(response)` | 解析 LLM 响应中的 JSON（支持 Markdown 代码块、修复常见格式问题） |
| `LLMClient.build_tool_schemas(workers)` | 从 Worker 元数据生成 OpenAI Function Calling tool schemas |
| `list_presets()` / `get_preset(name)` | 查询/获取模型预设 |

## 数据模型

- `ToolCallResult`: Function Calling 解析结果（worker, action, args, thinking, is_final）
- `ModelPreset`: 模型预设（name, model, base_url, supports_function_calling, context_window 等）

## 关键依赖

- `openai>=1.0.0`: AsyncOpenAI SDK

## 测试与质量

- `tests/test_llm_client.py`

## 相关文件清单

- `src/llm/__init__.py`
- `src/llm/client.py`
- `src/llm/presets.py`
