[根目录](../../CLAUDE.md) > [src](../) > **scheduler**

# scheduler 模块

## 变更记录 (Changelog)

| 时间 | 操作 | 说明 |
|------|------|------|
| 2026-02-19 21:48:49 | 新建 | 初始化架构师扫描生成 |

## 模块职责

基于 cron 表达式的定时任务调度器，支持模板周期执行。

## 入口与启动

- **`scheduler.py`** -- `CronField` 类（cron 表达式解析）和调度器实现。

## 对外接口

| 组件 | 说明 |
|------|------|
| `CronField` | 解析单个 cron 字段（分钟/小时/日/月/星期），支持 `*`, `,`, `-`, `/` 语法 |
| `JobStatus` | 任务状态: `active` / `paused` / `finished` |

## 数据模型

- `CronField`: cron 字段解析器
- `JobStatus`: Literal["active", "paused", "finished"]

## 测试与质量

- `tests/test_scheduler.py`

## 相关文件清单

- `src/scheduler/__init__.py`
- `src/scheduler/scheduler.py`
