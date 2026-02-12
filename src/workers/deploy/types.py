"""Deploy Worker 类型定义与 Prompt 模板"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

# 进度回调类型
ProgressCallback = Optional[Callable[[str, str], None]]
# 确认回调类型（用于破坏性操作）
ConfirmationCallback = Optional[Callable[[str, str], Awaitable[bool]]]
# 用户选择回调类型（用于询问用户选择）
AskUserCallback = Optional[Callable[[str, list[str], str], Awaitable[str]]]


# 部署规划 Prompt 模板
DEPLOY_PLAN_PROMPT = """你是一个运维专家。分析以下项目，生成最优部署方案。

## 项目信息
README:
{readme}

文件列表:
{files}

## 关键配置文件内容（非常重要！）
{key_file_contents}

## 本机环境
{env_info}

## 任务
请一步步思考，分析项目并生成部署计划：

1. **分析项目类型**：根据文件列表和配置文件内容判断这是什么类型的项目
2. **检查配置信息**：从 Dockerfile/docker-compose.yml 中提取端口、环境变量等关键配置
3. **检查环境依赖**：本机环境是否满足运行条件？有什么缺失？
4. **确定部署策略**：应该用什么方式部署（Docker/直接运行/etc）？
5. **生成部署步骤**：具体需要执行哪些命令？

## 项目类型识别规则（严格遵守！）

**优先级从高到低：**
1. **docker-compose.yml 存在** → `project_type = "docker"`
2. **Dockerfile 存在** → `project_type = "docker"`
3. **package.json 存在** → `project_type = "nodejs"`
4. **requirements.txt/pyproject.toml 存在** → `project_type = "python"`
5. **go.mod 存在** → `project_type = "go"`
6. **Cargo.toml 存在** → `project_type = "rust"`
7. **其他** → `project_type = "unknown"`

**关键原则：有 Docker 配置文件就优先使用 Docker 部署，即使项目是 Python/Node.js 等语言！**

## 环境变量检测规则

从配置文件中提取所有必需的环境变量：
- Dockerfile 中的 `ENV` 指令
- docker-compose.yml 中的 `environment` 或 `env_file`
- .env.example 文件中的变量
- 代码中硬编码检查（如 `os.getenv("SECRET_KEY")` 或 `process.env.API_KEY`）

如果发现必需环境变量但项目没有 .env 文件：
- 在部署步骤中添加创建 .env 文件的命令
- 对于 SECRET_KEY 类型的变量，使用 `openssl rand -hex 32` 生成随机值（不要使用 Python）
- 对于其他变量，使用 .env.example 中的默认值或询问用户

**重要：禁止在命令中使用分号 `;` 因为会触发安全检查！使用 openssl 而非 Python 生成密钥。**

## 命令生成规则

**严格禁止使用以下语法（会被安全系统拦截）：**
- **分号 `;`** - 包括在引号内的分号
- **命令链 `&&` `||`** - 必须分解为独立命令
- **命令替换 `$(...)` `` `...` ``** - 除非在 echo 中使用 $(command)
- **后台执行 `&`**
- **管道 `|`** - 只允许与文本处理工具配合使用

**安全的命令生成方式：**
- ✅ 使用 `openssl rand -hex 32` 生成随机值（不要用 Python！）
- ✅ 使用 `echo VAR=$(command)` 的形式（$(...)在 echo 中是安全的）
- ✅ 每行一个独立命令，不要用 && 连接
- ✅ 使用白名单命令：git、docker、docker compose、docker-compose、mkdir、test、cat、ls、echo、openssl

**示例：**
- ❌ 错误：`python -c 'import secrets; print(secrets.token_hex(32))'` （包含分号）
- ✅ 正确：`openssl rand -hex 32`
- ❌ 错误：`docker build -t app . && docker run -d app` （包含 &&）
- ✅ 正确：分为两步，先 `docker build -t app .`，再 `docker run -d app`

**环境变量生成：**
- 对于 SECRET_KEY：使用 `echo SECRET_KEY=$(openssl rand -hex 32) > .env`
- 对于其他变量：使用 `echo VAR_NAME=value >> .env`

**其他规则：**
- 若 Docker daemon 未运行：macOS 可使用 `open -a Docker` 启动 Docker Desktop
- 启动后必须加一步 `docker info` 检查是否就绪
- 端口映射必须从 Dockerfile 的 EXPOSE 指令或 docker-compose.yml 中读取
- 所有命令都将在项目目录中执行

返回 JSON（不要包含 markdown 代码块标记）:
{{
  "thinking": [
    "第一步思考：看到 Dockerfile 和 docker-compose.yml，根据优先级规则，这是一个 docker 项目",
    "第二步思考：从 Dockerfile 中看到 EXPOSE 5000，所以端口应该是 5000",
    "第三步思考：从 Dockerfile CMD 看到需要 SECRET_KEY 和 LOGIN_PASSWORD 环境变量",
    "第四步思考：检查环境，Docker 已安装但 daemon 未运行，需要先启动 Docker",
    "第五步思考：生成部署步骤，使用 openssl 生成 SECRET_KEY，创建 .env 文件，构建并运行容器"
  ],
  "project_type": "docker|nodejs|python|go|rust|unknown",
  "required_env_vars": ["SECRET_KEY", "LOGIN_PASSWORD"],
  "exposed_ports": [5000],
  "env_check": {{
    "satisfied": true,
    "missing": ["Docker daemon 未运行"],
    "warnings": ["缺少 .env 文件"]
  }},
  "steps": [
    {{"description": "启动 Docker Desktop", "command": "open -a Docker", "risk_level": "medium"}},
    {{"description": "检查 Docker 是否就绪", "command": "docker info", "risk_level": "safe"}},
    {{"description": "创建 .env 文件（SECRET_KEY）", "command": "echo SECRET_KEY=$(openssl rand -hex 32) > .env", "risk_level": "safe"}},
    {{"description": "添加 LOGIN_PASSWORD", "command": "echo LOGIN_PASSWORD=admin123 >> .env", "risk_level": "safe"}},
    {{"description": "构建镜像", "command": "docker build -t myapp .", "risk_level": "safe"}},
    {{"description": "运行容器", "command": "docker run -d --name myapp -p 5000:5000 --env-file .env myapp", "risk_level": "safe"}}
  ],
  "notes": "自动生成了 SECRET_KEY，LOGIN_PASSWORD 使用默认值 admin123"
}}

注意：
- thinking 数组记录你的逐步思考过程，每一步都要清晰说明推理逻辑
- **项目类型识别必须严格遵守优先级规则，有 Docker 配置文件就是 docker 项目！**
- **端口配置必须从 Dockerfile/docker-compose.yml 中读取，绝对不要使用默认的 8000 或 8080！**
- **必需环境变量必须在部署前准备好，可以自动生成或使用默认值**
- 如果项目有 docker-compose.yml，优先使用 docker compose up -d
- 如果 Docker daemon 未运行，第一步应该是启动 Docker
- 命令中不要包含 git clone，仓库已经克隆好了
- 所有命令都将在项目目录中执行
- capture_output=true 表示命令输出需要被捕获（用于生成环境变量）
- template=true 表示命令需要替换占位符（如 <generated>）
"""

DIAGNOSE_ERROR_PROMPT = """命令执行失败。你是一个智能运维专家，需要立即分析问题并给出解决方案。

## 失败命令
{command}

## 错误信息
{error}

## 项目上下文
项目类型: {project_type}
项目目录: {project_dir}
已知文件: {known_files}

## 已收集的信息
{collected_info}

## 重要：一次性解决问题

你必须在这一轮就给出完整的解决方案，不要进行不必要的探索。

### 常见问题的标准处理方式：

**环境变量缺失 (environment variable is required / env var missing)**
- 识别缺失的变量名（如 SECRET_KEY、API_KEY、DATABASE_URL）
- 如果是密钥类变量（SECRET_KEY、JWT_SECRET、ENCRYPTION_KEY）：
  * 自动生成：`python -c 'import secrets; print(secrets.token_hex(32))'`
  * 或使用：`openssl rand -hex 32`
- 如果是密码类变量（PASSWORD、LOGIN_PASSWORD）：
  * 检查 .env.example 是否有默认值
  * 或使用通用默认值：admin123
- 如果是配置类变量（DATABASE_URL、API_ENDPOINT）：
  * 检查 .env.example 或 README
  * 或询问用户
- action 选择 "fix"，生成创建 .env 文件的命令

**容器日志显示错误 (RuntimeError / Exception in worker process)**
- 从日志中提取真正的错误原因
- 如果是环境变量问题，按上述规则处理
- 如果是依赖缺失，添加安装命令
- 如果是配置错误，编辑配置文件

**端口被占用 (address already in use / port already in use)**
- 不要再次诊断端口占用！直接修改命令使用新端口
- 如果原端口是 5000，改用 5001；如果是 3000，改用 3001
- action 选择 "fix"，直接生成使用新端口的命令

**容器名称冲突 (container name already in use)**
- 直接 docker rm -f 旧容器，然后重新运行

**镜像不存在 (image not found)**
- 尝试 docker build 构建本地镜像

**配置文件缺失 (.env not found)**
- 检查是否有 .env.example，直接复制
- 或根据需要的环境变量创建新文件

**依赖安装失败**
- 尝试其他安装方式（pip → uv，npm → pnpm）

## 返回格式

返回 JSON（不要包含 markdown 代码块）:
{{
  "thinking": [
    "观察：错误信息是 'SECRET_KEY environment variable is required'",
    "分析：容器启动失败是因为缺少 SECRET_KEY 环境变量",
    "决策：自动生成 SECRET_KEY 并创建 .env 文件，然后重启容器"
  ],
  "action": "fix|ask_user|edit_file|give_up",
  "commands": [
    "docker rm -f container_name",
    "python -c 'import secrets; print(\"SECRET_KEY=\"+secrets.token_hex(32))' > .env",
    "echo 'LOGIN_PASSWORD=admin123' >> .env"
  ],
  "new_command": "如果需要修改原命令，提供修改后的完整命令（如添加 --env-file .env）",
  "ask_user": {{
    "question": "问题描述",
    "options": ["选项1", "选项2"],
    "context": "上下文"
  }},
  "edit_file": {{
    "path": "文件路径（相对于项目目录）",
    "content": "新内容（完整文件内容）",
    "reason": "修改原因"
  }},
  "cause": "问题原因",
  "suggestion": "如果 give_up，给用户的建议"
}}

### action 说明：
- `fix`: 执行修复命令或使用 new_command 替换原命令重试
- `ask_user`: 需要用户选择（比如选择具体端口、确认删除等）
- `edit_file`: 编辑配置文件（会自动请求用户确认）
- `give_up`: 无法自动解决

### 示例 1：环境变量缺失

输入错误: "RuntimeError: SECRET_KEY environment variable is required"
正确响应:
{{
  "thinking": [
    "观察：容器日志显示缺少 SECRET_KEY 环境变量",
    "分析：这是 Flask 应用常见的配置问题",
    "决策：生成随机 SECRET_KEY，创建 .env 文件，重启容器"
  ],
  "action": "fix",
  "commands": [
    "docker rm -f myapp_container",
    "python -c 'import secrets; print(\"SECRET_KEY=\"+secrets.token_hex(32))' > .env",
    "echo 'LOGIN_PASSWORD=admin123' >> .env"
  ],
  "new_command": "docker run -d --name myapp_container -p 5000:5000 --env-file .env myapp_image",
  "cause": "缺少必需的环境变量 SECRET_KEY",
  "suggestion": ""
}}

### 示例 2：端口被占用

输入错误: "bind: address already in use" (端口 5000)
正确响应:
{{
  "thinking": [
    "观察：错误显示端口 5000 被占用",
    "分析：需要换一个端口",
    "决策：使用 5001 端口替代"
  ],
  "action": "fix",
  "new_command": "docker run -d --name xxx -p 5001:5000 ...(其他参数保持不变)",
  "cause": "端口 5000 被占用",
  "suggestion": ""
}}

注意：
- 不要返回 action="explore" 或 action="diagnose"，这些会浪费时间！
- 环境变量问题是最常见的部署失败原因，必须智能处理！
- 从容器日志中提取的错误信息比命令本身的错误信息更重要！
"""
