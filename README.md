# OpsAI - 5 分钟学会运维

> 🚀 用自然语言操作服务器，无需记命令

**核心能力**：查日志 · 查状态 · 重启服务 · 检查资源 · 一键部署

## ⚡ 快速开始（3 步上手）

### 1️⃣ 安装
```bash
pip install opsai
# 或
uv tool install opsai
```

### 2️⃣ 启动
```bash
opsai-tui
```

### 3️⃣ 试试这 3 个命令
```
> 查看所有容器
> 查看磁盘空间
> 查看最近的日志
```

---

## 🎯 常见场景（点击查看示例）

<details>
<summary>🔴 <b>服务出问题了</b></summary>

```bash
# 场景 1：网站打不开
opsai-tui
> "我的网站打不开"
# → 自动检测 nginx 容器状态 + 端口监听 + 查看日志

# 场景 2：查看特定服务日志
> "查看 api-server 的日志"
# → 自动识别容器/systemd 服务，显示最近 100 行日志

# 场景 3：重启服务
> "重启 nginx"
# → 安全确认后执行重启，并验证启动成功
```
</details>

<details>
<summary>💾 <b>磁盘空间不足</b></summary>

```bash
opsai-tui
> "磁盘快满了，帮我清理"
# → 自动查找大文件 + 建议可清理的内容 + 安全删除
```
</details>

<details>
<summary>🚀 <b>部署 GitHub 项目</b></summary>

```bash
# 一键部署（自动检测项目类型）
opsai deploy https://github.com/user/my-app

# 或通过 TUI
opsai-tui
> "帮我部署 https://github.com/user/my-app"
```
</details>

<details>
<summary>🐌 <b>服务响应慢</b></summary>

```bash
opsai-tui
> "服务很慢，帮我看看"
# → 检查 CPU/内存占用 + 分析慢查询日志 + 建议优化方案
```
</details>

---

## 🔒 安全保障

- ✅ **危险操作拦截**：自动识别 `rm -rf`, `kill -9` 等高危命令
- ✅ **二次确认**：破坏性操作需要手动确认
- ✅ **Dry-run 模式**：预览操作，不实际执行
- ✅ **审计日志**：所有操作自动记录到 `~/.opsai/audit.log`

---

## 📖 进阶使用

### 配置 LLM
```bash
# 使用本地 Ollama（推荐）
opsai config set-llm --model qwen2.5:7b --base-url http://localhost:11434/v1

# 使用 OpenAI
opsai config set-llm --model gpt-4o --api-key sk-xxx
```

### CLI 模式（快速执行单条命令）
```bash
opsai query "查看磁盘使用情况"
opsai query "列出所有容器" --dry-run
```

### 一键部署
```bash
# 部署 GitHub 项目到默认目录
opsai deploy https://github.com/user/my-app

# 指定部署目录
opsai deploy https://github.com/user/my-app --target-dir ~/myprojects

# 预览部署（不实际执行）
opsai deploy https://github.com/user/my-app --dry-run
```

---

## ❓ 常见问题

**Q: 支持哪些运维工具？**
A: Docker、Systemd、通用 Shell 命令。

**Q: 需要 root 权限吗？**
A: 不需要。继承当前用户权限，不涉及提权。

**Q: 数据安全吗？**
A: 所有数据在本地处理，不上传到云端（LLM API 除外）。

**Q: 如何卸载？**
A: `pip uninstall opsai` + 删除 `~/.opsai/` 目录。

---

## 🛠️ 开发

```bash
# 克隆仓库
git clone https://github.com/yourusername/opsai.git
cd opsai

# 安装依赖
uv sync

# 运行测试
uv run pytest

# 类型检查
uv run mypy src/

# 代码格式化
uv run ruff format src/ tests/
```

## 📄 License

MIT License
