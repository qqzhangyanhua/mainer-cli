# 服务器资产台账上下文注入

**日期**: 2026-02-23
**状态**: 已批准
**方案**: 方案 A — 纯 Prompt 注入

## 需求

用户维护一份 Markdown 自由文本文件，描述服务器资产信息（服务拓扑、部署路径、端口、存储位置等）。OpsAI 在每次 ReAct 推理时将该文件内容注入 system prompt，使 LLM 始终具备服务器基础设施的上下文感知能力。

### 用途

- **资产台账**：记录服务器上运行的服务、端口、路径等信息
- **运维上下文增强**：用户问"前端部署在哪"时，LLM 可直接从台账中回答

## 文件规约

- **路径**: `~/.opsai/inventory.md`
- **格式**: Markdown 自由文本，不做结构化约束
- **粒度**: 单文件，所有服务器信息集中管理

### 示例内容

```markdown
# 生产环境

## 服务器 A (192.168.1.100)
- 前端应用：Nginx 反代，静态资源 OSS 同步到 /opt/html
- 后端 API：Spring Boot，端口 8080，部署在 /opt/api，使用 systemd 管理
- MySQL 5.7：端口 3306，数据目录 /var/lib/mysql

## 服务器 B (192.168.1.101)
- Redis 集群节点，端口 6379-6381
- 定时任务：crontab 每日凌晨 3 点备份数据库到 /backup/mysql/

# 测试环境
...
```

## 代码改动

### 唯一改动文件: `src/orchestrator/prompt.py`

在 `build_system_prompt()` 方法中，`env_context` 之后读取 `~/.opsai/inventory.md`，原文拼入 prompt：

```python
inventory_section = ""
inventory_path = Path("~/.opsai/inventory.md").expanduser()
if inventory_path.exists():
    content = inventory_path.read_text(encoding="utf-8").strip()
    if content:
        inventory_section = f"\n\n## Server inventory (infrastructure context)\n{content}"
```

在 system prompt 模板中 `{env_context}` 后追加 `{inventory_section}`。

### 不做的事

- 不新增配置项（路径固定）
- 不做文件大小限制
- 不做任何解析/验证（LLM 直接消费原文）
- 不新建文件/类/抽象层

### 改动量

约 10 行。

## 测试

在 `tests/test_prompt.py` 新增测试用例：

1. `inventory.md` 存在时，system prompt 包含 `Server inventory` 段和文件内容
2. 文件不存在时，system prompt 不包含该段

使用 `tmp_path` + `monkeypatch` mock 路径，不污染真实文件系统。

## 决策记录

| 方案 | 描述 | 结论 |
|------|------|------|
| A. 纯 Prompt 注入 | 读文件拼字符串，零抽象 | **采纳** |
| B. ContextProvider 抽象层 | 新建 InventoryProvider 接口 | 过度设计，拒绝 |
| C. Inventory Worker | 通过 Function Calling 按需查询 | 与"始终注入"需求矛盾，拒绝 |
