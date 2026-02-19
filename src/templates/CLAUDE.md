[根目录](../../CLAUDE.md) > [src](../) > **templates**

# templates 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

任务模板管理与执行。定义可复用的运维流程模板（多步骤 Worker 指令序列），支持条件执行、失败重试和步骤间结果传递。

## 入口与启动

- **`manager.py`** -- `TemplateManager` 类，模板加载/列出/生成指令。
- **`executor.py`** -- 模板执行器。

## 对外接口

| 方法 | 说明 |
|------|------|
| `TemplateManager.list_templates()` | 列出所有可用模板 |
| `TemplateManager.load_template(name)` | 加载指定模板 |
| `TemplateManager.generate_instructions(template, context)` | 从模板生成指令序列 |

## 数据模型

- `TaskTemplate`: 任务模板（name, description, category, steps）
- `TemplateStep`: 模板步骤（worker, action, args, output_key, condition, on_failure, retry_count）
- `OnFailureAction`: Literal["abort", "skip", "retry"]

## 测试与质量

- `tests/test_templates.py`

## 相关文件清单

- `src/templates/__init__.py`
- `src/templates/manager.py`
- `src/templates/executor.py`
