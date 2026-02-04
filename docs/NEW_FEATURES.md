# 新功能说明文档

本文档介绍 OpsAI v0.2 版本新增的三大核心功能。

## 1. ContainerWorker - Docker 容器管理

### 功能概述
原生支持 Docker 容器的完整生命周期管理，无需编写复杂的 Docker 命令。

### 支持的操作
- **list_containers**: 列出所有容器（可过滤运行中/已停止）
- **inspect_container**: 查看容器详细信息
- **logs**: 获取容器日志（支持 tail）
- **restart**: 重启容器
- **stop**: 停止容器
- **start**: 启动容器
- **stats**: 获取容器资源统计（CPU、内存）

### 使用示例

```bash
# 列出所有运行中的容器
opsai query "列出所有容器"

# 查看容器状态
opsai query "查看容器 my-app 的状态"

# 获取容器日志（最近 100 行）
opsai query "查看容器 my-app 的日志"

# 重启容器（需要 TUI 确认）
opsai-tui
> "重启容器 my-app"
```

### 安全级别
- `list_containers`, `inspect_container`, `logs`, `stats`: **safe**（可在 CLI 模式直接执行）
- `restart`, `stop`, `start`: **medium**（需要在 TUI 模式确认）

---

## 2. Dry-run 模式 - 预览执行

### 功能概述
在不实际执行操作的情况下，预览命令的执行结果和影响范围，极大提高生产环境安全性。

### 工作原理
- 所有 Worker 支持 `dry_run` 参数
- Dry-run 模式下返回 `simulated=True` 标记
- 不依赖外部资源（如 Docker 连接）
- 返回详细的操作描述

### 使用示例

```bash
# CLI 单次查询 dry-run
opsai query "删除 /tmp 下的临时文件" --dry-run

# 模板 dry-run 执行
opsai template run disk_cleanup --dry-run
```

### 配置选项

在 `~/.opsai/config.json` 中：

```json
{
  "safety": {
    "dry_run_by_default": false,
    "require_dry_run_for_high_risk": true
  }
}
```

- **dry_run_by_default**: 默认启用 dry-run（推荐生产环境设为 `true`）
- **require_dry_run_for_high_risk**: 高风险操作强制先 dry-run

### 示例输出

```
Step 1/2: check_disk_usage
✓ [DRY-RUN] Would check disk usage for / (simulated)

Step 2/2: find_large_files
✓ [DRY-RUN] Would search for files larger than 100MB in /var/log (simulated)
```

---

## 3. 任务模板系统

### 功能概述
预定义的多步骤运维流程，支持变量注入，实现"一键运维"。

### 核心概念

#### 模板结构
```yaml
name: "disk_cleanup"
description: "磁盘空间清理标准流程"
category: "maintenance"
steps:
  - worker: system
    action: check_disk_usage
    args:
      path: "/"
    description: "检查根目录磁盘使用情况"
  - worker: system
    action: find_large_files
    args:
      path: "/var/log"
      min_size_mb: 100
```

### 预置模板

| 模板名称                | 分类              | 步骤数 | 说明                     |
|----------------------|------------------|-------|-------------------------|
| disk_cleanup         | maintenance      | 2     | 磁盘空间清理              |
| container_health_check | container       | 1     | 容器健康检查              |
| service_restart      | container        | 2     | 服务重启标准流程          |
| log_analysis         | troubleshooting  | 1     | 日志错误分析              |

### 使用示例

```bash
# 列出所有模板
opsai template list

# 查看模板详情
opsai template show disk_cleanup

# 运行模板
opsai template run disk_cleanup

# Dry-run 模式
opsai template run disk_cleanup --dry-run

# 带上下文变量（用于占位符替换）
opsai template run service_restart \
  --context '{"container_id": "my-app"}'
```

### 变量注入

模板支持 `{{ variable }}` 占位符：

```json
{
  "worker": "container",
  "action": "restart",
  "args": {
    "container_id": "{{ container_id }}"
  }
}
```

运行时注入：
```bash
opsai template run service_restart \
  --context '{"container_id": "nginx"}'
```

### 自定义模板

模板存储在 `~/.opsai/templates/` 目录，格式为 JSON：

```bash
# 创建自定义模板
cat > ~/.opsai/templates/my_flow.json << 'EOF'
{
  "name": "my_flow",
  "description": "我的自定义流程",
  "category": "custom",
  "steps": [
    {
      "worker": "system",
      "action": "check_disk_usage",
      "args": {"path": "/"},
      "description": "检查磁盘"
    }
  ]
}
EOF

# 运行自定义模板
opsai template run my_flow
```

---

## 集成使用示例

### 场景 1：安全的容器维护

```bash
# 1. Dry-run 预览
opsai template run service_restart \
  --context '{"container_id": "api-server"}' \
  --dry-run

# 2. 确认无误后实际执行
opsai template run service_restart \
  --context '{"container_id": "api-server"}'
```

### 场景 2：生产环境强制 Dry-run

编辑 `~/.opsai/config.json`：
```json
{
  "safety": {
    "dry_run_by_default": true,
    "require_dry_run_for_high_risk": true
  }
}
```

此后所有操作默认 dry-run，需显式使用 `--no-dry-run` 才能实际执行。

### 场景 3：自动化巡检

```bash
# 创建巡检模板
cat > ~/.opsai/templates/daily_check.json << 'EOF'
{
  "name": "daily_check",
  "description": "每日健康巡检",
  "category": "monitoring",
  "steps": [
    {"worker": "system", "action": "check_disk_usage", "args": {"path": "/"}},
    {"worker": "container", "action": "list_containers", "args": {"all": false}}
  ]
}
EOF

# 定时执行（配合 cron）
0 9 * * * /usr/local/bin/opsai template run daily_check
```

---

## 技术实现细节

### Dry-run 机制
1. 在 `Instruction` 中添加 `dry_run: bool` 字段
2. 在 `WorkerResult` 中添加 `simulated: bool` 标记
3. 每个 Worker 的 `execute()` 方法支持 `dry_run` 参数
4. Orchestrator 全局支持 dry-run 注入

### 模板系统架构
- **TemplateManager**: 模板加载、保存、删除
- **TemplateStep**: 单步操作定义
- **TaskTemplate**: 完整模板定义
- **变量替换**: 支持 `{{ variable }}` 语法

### 安全增强
- 新增 `delete_files` 为 **high** 风险操作
- 容器 `restart`/`stop` 为 **medium** 风险
- Dry-run 模式不触发审计日志写入

---

## 升级说明

### 依赖更新
```bash
# 安装 Docker 支持（可选）
pip install docker>=7.0.0
```

### 配置迁移
旧配置文件会自动兼容，新增配置项：
```json
{
  "safety": {
    "dry_run_by_default": false,
    "require_dry_run_for_high_risk": true
  }
}
```

### 测试验证
```bash
# 运行单元测试
pytest tests/test_dry_run.py
pytest tests/test_templates.py
pytest tests/test_container_worker.py
```

---

## 最佳实践

1. **生产环境**：设置 `dry_run_by_default=true`
2. **高危操作**：始终先 dry-run，确认后执行
3. **模板化**：将常见运维流程封装为模板
4. **审计日志**：定期检查 `~/.opsai/audit.log`
5. **容器安全**：容器操作使用 TUI 模式，避免误操作

---

## 常见问题

### Q: Dry-run 是否记录审计日志？
A: 不记录。Dry-run 仅模拟，不触发实际操作和日志。

### Q: Docker 未运行时 dry-run 是否可用？
A: 可用。Dry-run 模式不依赖 Docker 连接。

### Q: 模板变量未提供会怎样？
A: 保持原样（如 `"{{ container_id }}"`），可能导致执行失败。

### Q: 如何查看所有可用的 Worker 操作？
A: 查看各 Worker 的 `get_capabilities()` 方法或文档。

---

## 路线图

未来版本计划：
- [ ] 模板市场（社区共享）
- [ ] 可视化模板编辑器
- [ ] 模板执行历史记录
- [ ] 更多预置模板（Kubernetes、监控等）
- [ ] 模板权限控制
