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

**重要**：
- 端口映射必须从 Dockerfile 的 EXPOSE 指令或 docker-compose.yml 中读取，不要瞎猜！
- 如果 Dockerfile 中有 EXPOSE 5000，那就用 -p 5000:5000
- 如果 docker-compose.yml 中有 ports: ["5000:5000"]，那就用这个
- 环境变量也要从配置文件中读取

返回 JSON（不要包含 markdown 代码块标记）:
{{
  "thinking": [
    "第一步思考：看到 Dockerfile 和 requirements.txt，说明这是一个 Python 项目，支持 Docker 部署",
    "第二步思考：从 Dockerfile 中看到 EXPOSE 5000，所以端口应该是 5000",
    "第三步思考：检查环境，Docker 已安装但 daemon 未运行，需要先启动 Docker",
    "第四步思考：生成部署步骤..."
  ],
  "project_type": "python/nodejs/docker/go/rust/unknown",
  "env_check": {{
    "satisfied": true,
    "missing": ["Docker daemon 未运行"],
    "warnings": ["建议先启动 Docker Desktop"]
  }},
  "steps": [
    {{"description": "启动 Docker Desktop", "command": "open -a Docker", "risk_level": "safe"}},
    {{"description": "构建镜像", "command": "docker build -t myapp .", "risk_level": "safe"}},
    {{"description": "运行容器", "command": "docker run -d --name myapp -p 5000:5000 myapp", "risk_level": "safe"}}
  ],
  "notes": "任何需要注意的事项"
}}

注意：
- thinking 数组记录你的逐步思考过程，每一步都要清晰说明推理逻辑
- **端口配置必须从 Dockerfile/docker-compose.yml 中读取，绝对不要使用默认的 8000 或 8080！**
- 如果项目有 docker-compose.yml，优先使用 docker compose up -d
- 如果 Docker daemon 未运行，第一步应该是启动 Docker
- 命令中不要包含 git clone，仓库已经克隆好了
- 所有命令都将在项目目录中执行
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

**依赖安装失败**
- 尝试其他安装方式（pip → uv，npm → pnpm）

## 返回格式

返回 JSON（不要包含 markdown 代码块）:
{{
  "thinking": [
    "观察：错误信息是 xxx",
    "分析：这说明 yyy",
    "决策：我应该 zzz"
  ],
  "action": "fix|ask_user|edit_file|give_up",
  "commands": ["修复命令1", "修复命令2"],
  "new_command": "如果需要修改原命令，提供修改后的完整命令",
  "ask_user": {{
    "question": "问题描述",
    "options": ["选项1", "选项2"],
    "context": "上下文"
  }},
  "edit_file": {{
    "path": "文件路径",
    "content": "新内容",
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

### 示例：端口 5000 被占用

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

注意：不要返回 action="explore" 或 action="diagnose"，这些会浪费时间！
"""
