# GitHub 项目智能部署功能设计

> 日期: 2026-02-05

## 概述

实现智能部署功能：用户提供 GitHub URL，LLM 自动读取 README、分析项目结构、选择最佳部署方式并执行。

## 需求总结

| 项目 | 决策 |
|------|------|
| 触发方式 | 自动识别意图（闲聊 / 分析 / 部署） |
| 决策者 | LLM 自主读取 README，选择部署方式 |
| 获取内容 | 直接 HTTP + Tavily 搜索补充 |
| 部署目标 | 用户指定目录，默认 `~/projects/` |
| 安全机制 | LLM 根据命令内容判断风险等级 |

## 整体架构

### 新增组件

```
src/workers/
├── http.py          # HttpWorker - 通用 HTTP 请求
└── tavily.py        # TavilyWorker - 搜索 + 内容提取

src/orchestrator/
└── prompt.py        # 扩展：新增 DEPLOY_INTENT_PROMPT 模板
```

### ReAct 循环流程（部署场景）

```
用户: "帮我部署 https://github.com/user/repo"
         ↓
1. RequestPreprocessor.detect_intent() → "deploy"
         ↓
2. PromptBuilder 使用 DEPLOY_INTENT_PROMPT 模板
         ↓
3. LLM 生成指令: HttpWorker.fetch_github_readme
         ↓
4. LLM 分析 README，决定部署方式
         ↓
5. LLM 生成指令: ShellWorker.execute_command (git clone / docker compose)
         ↓
6. 如果 README 信息不足 → TavilyWorker.search 补充
         ↓
7. 循环直到部署完成
```

### 关键设计决策

- Worker 保持"愚蠢"，只负责执行单一操作
- 所有编排逻辑由 LLM 在 ReAct 循环中完成
- 部署专用 prompt 提供引导，但不限制 LLM 的决策自由度

---

## HttpWorker 设计

**文件位置：** `src/workers/http.py`

### 支持的 Actions

| Action | 参数 | 说明 |
|--------|------|------|
| `fetch_url` | `url: str` | 获取任意 URL 内容，返回原始文本 |
| `fetch_github_readme` | `repo_url: str` | 解析 GitHub URL，获取 README.md 内容 |
| `list_github_files` | `repo_url: str`, `path: str = ""` | 列出仓库文件结构（检查 Dockerfile 等） |

### 实现细节

```python
# fetch_github_readme 内部逻辑
# https://github.com/user/repo → https://raw.githubusercontent.com/user/repo/main/README.md

# list_github_files 使用 GitHub API
# GET https://api.github.com/repos/{owner}/{repo}/contents/{path}
```

### 风险等级

- 所有 HTTP 读取操作标记为 `safe`（只读）

### 错误处理

- URL 格式错误 → 返回失败，提示正确格式
- 404 → 尝试 `master` 分支（部分老仓库）
- Rate limit → 返回失败，建议配置 GitHub Token

### 类型定义（新增到 types.py）

```python
class GitHubFileInfo(TypedDict):
    name: str
    type: Literal["file", "dir"]
    path: str
```

---

## TavilyWorker 设计

**文件位置：** `src/workers/tavily.py`

### 支持的 Actions

| Action | 参数 | 说明 |
|--------|------|------|
| `search` | `query: str`, `max_results: int = 5` | 搜索相关信息，返回摘要列表 |
| `extract` | `url: str` | 提取网页内容，去除噪音返回结构化文本 |

### 使用场景

```
场景1: README 不清晰
LLM: "README 没有部署说明，搜索一下"
→ TavilyWorker.search("how to deploy projectname")

场景2: 需要官方文档补充
LLM: "需要查看官方部署文档"
→ TavilyWorker.extract("https://docs.project.io/deploy")
```

### 配置管理

在 `~/.opsai/config.json` 中新增：

```python
class TavilyConfig(BaseModel):
    api_key: str = ""
    timeout: int = 30
```

### 风险等级

- `search` / `extract` 均为 `safe`（只读）

### 类型定义（新增到 types.py）

```python
class TavilySearchResult(TypedDict):
    title: str
    url: str
    content: str  # 摘要
    score: float  # 相关性分数
```

### 依赖

- 新增 `tavily-python` 到 pyproject.toml

### 降级策略

- 如果未配置 API Key → Worker 返回错误提示用户配置
- 不影响其他功能正常使用

---

## 部署意图 Prompt 模板

**文件位置：** `src/orchestrator/prompt.py`

### 意图识别扩展

当前 `RequestPreprocessor` 支持的意图类型：
- `chat` → 闲聊
- `task` → 运维任务

新增：
- `deploy` → 部署项目

### 检测规则

```python
# 触发 deploy 意图的条件：
# 1. 包含 GitHub/GitLab URL
# 2. 且包含部署相关词汇：部署、deploy、安装、启动、运行
```

### DEPLOY_INTENT_PROMPT 模板

```
你是一个智能部署助手。用户希望部署一个 GitHub 项目。

## 部署流程指引

1. 首先使用 http.fetch_github_readme 获取项目 README
2. 使用 http.list_github_files 检查是否存在:
   - Dockerfile / docker-compose.yml → 优先 Docker 部署
   - package.json → Node.js 项目
   - requirements.txt / pyproject.toml → Python 项目
   - Makefile → 检查是否有 install/build 目标

3. 根据分析结果选择部署方式:
   - Docker: git clone → docker compose up -d
   - Node.js: git clone → npm install → npm start
   - Python: git clone → pip install / uv sync → 启动命令

4. 如果 README 信息不足，使用 tavily.search 搜索部署方法

5. 执行部署时，根据命令的破坏性评估风险等级:
   - safe: git clone, docker pull
   - medium: npm install, pip install, docker compose up
   - high: 涉及 sudo、删除、覆盖现有文件

## 用户请求
{user_input}

## 部署目标目录
{target_dir}
```

### Prompt 选择逻辑

```python
# PromptBuilder.build_system_prompt()
if intent == "deploy":
    return self.DEPLOY_INTENT_PROMPT.format(...)
elif intent == "chat":
    return self.CHAT_PROMPT
else:
    return self.TASK_PROMPT  # 现有逻辑
```

---

## 意图识别扩展

**文件位置：** `src/orchestrator/preprocessor.py`

### 意图类型扩展

当前：
```python
Intent = Literal["chat", "task"]
```

扩展为：
```python
Intent = Literal["chat", "task", "deploy"]
```

### deploy 意图检测逻辑

```python
def detect_intent(self, user_input: str) -> Intent:
    # 1. 检测 GitHub/GitLab URL 模式
    url_pattern = r'https?://(?:github|gitlab)\.com/[\w\-]+/[\w\-]+'
    has_repo_url = re.search(url_pattern, user_input) is not None

    # 2. 检测部署相关关键词
    deploy_keywords = ["部署", "deploy", "安装", "install", "启动", "运行", "跑起来"]
    has_deploy_intent = any(kw in user_input.lower() for kw in deploy_keywords)

    # 3. 组合判断
    if has_repo_url and has_deploy_intent:
        return "deploy"
    elif self._is_chat(user_input):
        return "chat"
    else:
        return "task"
```

### URL 提取工具函数

```python
def extract_repo_url(self, user_input: str) -> Optional[str]:
    """从用户输入中提取仓库 URL"""
    match = re.search(r'https?://(?:github|gitlab)\.com/[\w\-]+/[\w\-]+', user_input)
    return match.group(0) if match else None
```

### 类型定义更新（types.py）

```python
Intent = Literal["chat", "task", "deploy"]
```

---

## 错误处理与边界情况

### 网络请求错误

| 错误类型 | 处理方式 |
|----------|----------|
| 连接超时 | 返回失败，建议用户检查网络 |
| 404 Not Found | README: 尝试 master 分支；文件列表: 提示仓库不存在或私有 |
| 403 Rate Limit | 提示配置 GitHub Token |
| 私有仓库 | 提示需要配置访问 Token |

### 部署执行错误

| 场景 | 处理方式 |
|------|----------|
| 目标目录已存在同名文件夹 | LLM 判断：询问用户是否覆盖，或自动添加后缀 |
| git clone 失败 | 返回错误信息，不继续后续步骤 |
| docker compose 失败 | 返回日志，让 LLM 分析原因并建议修复 |
| 依赖安装失败 | 返回错误，让 LLM 搜索解决方案 |

### 边界情况

| 场景 | 处理方式 |
|------|----------|
| 非 GitHub/GitLab URL | 提示当前仅支持 GitHub/GitLab |
| URL 指向非仓库页面（如 issue） | 尝试解析，失败则提示用户提供正确的仓库地址 |
| README 不存在 | 使用 list_github_files 分析项目结构，或 Tavily 搜索 |
| README 是非英文/中文 | 直接传给 LLM 处理，不做额外翻译 |

### 超时配置

```python
# config/manager.py
class HttpConfig(BaseModel):
    timeout: int = 30  # 秒
    github_token: str = ""  # 可选，用于私有仓库和提高 rate limit
```

---

## 配置管理与 Worker 注册

### 配置更新（config/manager.py）

```python
class HttpConfig(BaseModel):
    timeout: int = 30
    github_token: str = ""  # 可选

class TavilyConfig(BaseModel):
    api_key: str = ""
    timeout: int = 30

class OpsAIConfig(BaseModel):
    llm: LLMConfig
    safety: SafetyConfig
    audit: AuditConfig
    http: HttpConfig = HttpConfig()      # 新增
    tavily: TavilyConfig = TavilyConfig()  # 新增
```

### CLI 配置命令扩展

```bash
# 配置 GitHub Token
opsai config set-http --github-token ghp_xxxx

# 配置 Tavily API Key
opsai config set-tavily --api-key tvly-xxxx
```

### Worker 注册（orchestrator/engine.py）

```python
def __init__(self, ...):
    # 现有 Workers
    self._workers: dict[str, BaseWorker] = {
        "system": SystemWorker(),
        "audit": AuditWorker(),
    }

    # ... 其他现有 Workers ...

    # 新增 HttpWorker
    from src.workers.http import HttpWorker
    self._workers["http"] = HttpWorker(self._config.http)

    # 新增 TavilyWorker（仅当配置了 API Key）
    if self._config.tavily.api_key:
        from src.workers.tavily import TavilyWorker
        self._workers["tavily"] = TavilyWorker(self._config.tavily)
```

### Prompt 能力注册（orchestrator/prompt.py）

```python
WORKER_CAPABILITIES: dict[str, list[str]] = {
    # 现有...
    "http": ["fetch_url", "fetch_github_readme", "list_github_files"],
    "tavily": ["search", "extract"],
}
```

---

## 测试策略

### 测试文件

```
tests/
├── test_http_worker.py      # HttpWorker 单元测试
├── test_tavily_worker.py    # TavilyWorker 单元测试
├── test_deploy_intent.py    # 部署意图识别测试
└── test_deploy_integration.py  # 端到端集成测试
```

### HttpWorker 单元测试

| 测试用例 | 说明 |
|----------|------|
| `test_fetch_github_readme_success` | 正常获取 README |
| `test_fetch_github_readme_master_fallback` | main 分支 404 时回退到 master |
| `test_fetch_github_readme_not_found` | 仓库不存在返回错误 |
| `test_list_github_files_success` | 列出文件结构 |
| `test_list_github_files_has_dockerfile` | 检测 Dockerfile 存在 |
| `test_fetch_url_timeout` | 超时处理 |

### TavilyWorker 单元测试

| 测试用例 | 说明 |
|----------|------|
| `test_search_success` | 正常搜索返回结果 |
| `test_search_no_results` | 无结果时的处理 |
| `test_extract_success` | 提取网页内容 |
| `test_no_api_key_error` | 未配置 API Key 时的错误提示 |

### 意图识别测试

```python
@pytest.mark.parametrize("input,expected", [
    ("帮我部署 https://github.com/user/repo", "deploy"),
    ("https://github.com/user/repo 这个项目怎么跑起来", "deploy"),
    ("你好", "chat"),
    ("检查磁盘使用情况", "task"),
    ("https://github.com/user/repo 这是什么项目", "task"),  # 无部署意图
])
def test_detect_intent(input, expected):
    ...
```

### Mock 策略

- HTTP 请求使用 `responses` 或 `httpx_mock` 库 mock
- Tavily API 使用 `unittest.mock.patch` mock

---

## 实现优先级

1. **P0 - 核心功能**
   - HttpWorker (`fetch_github_readme`, `list_github_files`)
   - 意图识别扩展 (`deploy` intent)
   - DEPLOY_INTENT_PROMPT 模板

2. **P1 - 增强功能**
   - TavilyWorker
   - 配置管理 CLI 命令

3. **P2 - 完善**
   - 完整测试覆盖
   - 错误处理边界情况
