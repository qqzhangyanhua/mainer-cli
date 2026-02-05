"""GitHub 项目部署 Worker - LLM 驱动的智能部署"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from collections.abc import Awaitable, Callable
from typing import Optional, Union, cast

from src.llm.client import LLMClient
from src.types import ArgValue, WorkerResult
from src.workers.base import BaseWorker
from src.workers.http import HttpWorker
from src.workers.shell import ShellWorker

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


class DeployWorker(BaseWorker):
    """GitHub 项目部署 Worker - LLM 驱动的智能部署

    核心理念：
    - 不再使用硬编码规则，由 LLM 分析项目并生成部署计划
    - 遇到错误时自动诊断并重试
    - 只在需要 sudo 或破坏性操作时询问用户

    支持的操作:
    - deploy: 一键智能部署（LLM 驱动）
    """

    def __init__(
        self,
        http_worker: HttpWorker,
        shell_worker: ShellWorker,
        llm_client: LLMClient,
        progress_callback: ProgressCallback = None,
        confirmation_callback: ConfirmationCallback = None,
        ask_user_callback: AskUserCallback = None,
    ) -> None:
        """初始化 DeployWorker

        Args:
            http_worker: HTTP Worker 实例
            shell_worker: Shell Worker 实例
            llm_client: LLM 客户端实例
            progress_callback: 进度回调函数，接收 (step_name, message)
            confirmation_callback: 确认回调函数，用于破坏性操作确认
            ask_user_callback: 用户选择回调函数，用于询问用户选择
        """
        self._http = http_worker
        self._shell = shell_worker
        self._llm = llm_client
        self._progress_callback = progress_callback
        self._confirmation_callback = confirmation_callback
        self._ask_user_callback = ask_user_callback

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """设置进度回调（允许后续注入）"""
        self._progress_callback = callback

    def set_confirmation_callback(self, callback: ConfirmationCallback) -> None:
        """设置确认回调（允许后续注入）"""
        self._confirmation_callback = callback

    def set_ask_user_callback(self, callback: AskUserCallback) -> None:
        """设置用户选择回调（允许后续注入）"""
        self._ask_user_callback = callback

    def _report_progress(self, step: str, message: str) -> None:
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(step, message)

    @property
    def name(self) -> str:
        return "deploy"

    def get_capabilities(self) -> list[str]:
        return ["deploy"]

    async def execute(
        self,
        action: str,
        args: dict[str, ArgValue],
    ) -> WorkerResult:
        """执行部署操作"""
        if action == "deploy":
            return await self._intelligent_deploy(args)
        else:
            return WorkerResult(
                success=False,
                message=f"Unknown action: {action}",
            )

    def _parse_github_url(self, url: str) -> Optional[tuple[str, str]]:
        """解析 GitHub URL，提取 owner 和 repo"""
        pattern = r"https?://github\.com/([\w\-\.]+)/([\w\-\.]+?)(?:\.git)?/?$"
        match = re.match(pattern, url)
        if match:
            return (match.group(1), match.group(2))
        return None

    async def _collect_env_info(self) -> dict[str, str]:
        """收集本机环境信息"""
        env_info: dict[str, str] = {
            "os": "unknown",
            "python": "unknown",
            "docker": "not installed",
            "docker_running": "no",
            "node": "not installed",
            "uv": "not installed",
        }

        # 检测操作系统
        import platform
        env_info["os"] = f"{platform.system()} {platform.release()}"

        # 检测 Python 版本
        python_result = await self._shell.execute(
            "execute_command",
            {"command": "python3 --version 2>/dev/null || python --version 2>/dev/null"},
        )
        if python_result.success and python_result.data:
            stdout = python_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["python"] = stdout.strip()

        # 检测 Docker 版本
        docker_result = await self._shell.execute(
            "execute_command",
            {"command": "docker --version 2>/dev/null"},
        )
        if docker_result.success and docker_result.data:
            stdout = docker_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["docker"] = stdout.strip()

                # 检测 Docker daemon 是否运行
                docker_info_result = await self._shell.execute(
                    "execute_command",
                    {"command": "docker info >/dev/null 2>&1 && echo 'running' || echo 'stopped'"},
                )
                if docker_info_result.success and docker_info_result.data:
                    info_stdout = docker_info_result.data.get("stdout", "")
                    if isinstance(info_stdout, str) and "running" in info_stdout:
                        env_info["docker_running"] = "yes"
                    else:
                        env_info["docker_running"] = "no (Docker Desktop not started)"

        # 检测 Node 版本
        node_result = await self._shell.execute(
            "execute_command",
            {"command": "node --version 2>/dev/null"},
        )
        if node_result.success and node_result.data:
            stdout = node_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["node"] = stdout.strip()

        # 检测 uv 版本
        uv_result = await self._shell.execute(
            "execute_command",
            {"command": "uv --version 2>/dev/null"},
        )
        if uv_result.success and uv_result.data:
            stdout = uv_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["uv"] = stdout.strip()

        return env_info

    async def _read_local_file(self, project_dir: str, filename: str, max_lines: int = 100) -> str:
        """安全读取本地文件内容"""
        file_path = os.path.join(project_dir, filename)
        try:
            if not os.path.exists(file_path):
                return ""
            if not os.path.isfile(file_path):
                return ""
            if os.path.getsize(file_path) > 50000:  # 50KB 限制
                return "(文件过大，跳过)"

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                content = "".join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (截断，仅显示前 {max_lines} 行)"
                return content
        except Exception as e:
            return f"(读取失败: {e})"

    async def _collect_key_file_contents(self, project_dir: str, key_files: list[str]) -> str:
        """收集关键配置文件的内容"""
        # 优先级：这些文件对部署最重要
        priority_files = [
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env.example",
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Makefile",
            "README.md",
            "README",
        ]

        contents: list[str] = []
        files_read = 0
        max_files = 5  # 最多读取 5 个文件，避免 prompt 过长

        for filename in priority_files:
            if files_read >= max_files:
                break

            # 检查文件是否存在于项目中
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                content = await self._read_local_file(project_dir, filename)
                if content and not content.startswith("("):
                    contents.append(f"=== {filename} ===\n{content}")
                    files_read += 1

        if not contents:
            return "(无关键配置文件)"

        return "\n\n".join(contents)

    async def _llm_generate_plan(
        self,
        readme: str,
        files: list[str],
        env_info: dict[str, str],
        project_dir: str = "",
    ) -> tuple[list[dict[str, str]], str, str, list[str]]:
        """LLM 生成部署计划

        Returns:
            (steps, project_type, notes, thinking)
        """
        # 截断过长内容
        readme_truncated = readme[:3000] if readme else "(无 README)"
        files_str = ", ".join(files[:50]) if files else "(无文件列表)"
        env_str = "\n".join(f"- {k}: {v}" for k, v in env_info.items())

        # 读取本地关键文件内容（这是关键！）
        key_file_contents = "(项目尚未克隆)"
        if project_dir:
            self._report_progress("deploy", "  读取本地配置文件...")
            key_file_contents = await self._collect_key_file_contents(project_dir, files)
            if not key_file_contents or key_file_contents == "(无关键配置文件)":
                key_file_contents = "(无关键配置文件，请根据文件名推断)"

        prompt = DEPLOY_PLAN_PROMPT.format(
            readme=readme_truncated,
            files=files_str,
            key_file_contents=key_file_contents,
            env_info=env_str,
        )

        response = await self._llm.generate(
            "You are an ops expert. Return only valid JSON without markdown code blocks.",
            prompt,
        )

        parsed = self._llm.parse_json_response(response)
        if not parsed:
            return [], "unknown", "LLM 返回格式错误", []

        # 提取思考过程
        thinking = parsed.get("thinking", [])
        if not isinstance(thinking, list):
            thinking = []

        steps = parsed.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        project_type = str(parsed.get("project_type", "unknown"))
        notes = str(parsed.get("notes", ""))

        return steps, project_type, notes, thinking

    def _try_local_fix(
        self,
        command: str,
        error: str,
    ) -> Optional[dict[str, object]]:
        """尝试本地规则修复（不依赖 LLM）

        对于常见问题使用硬编码规则快速修复，避免 LLM 解析失败

        Returns:
            修复方案字典，无法本地修复返回 None
        """
        error_lower = error.lower()

        # 端口占用：直接换端口
        if "address already in use" in error_lower or "port" in error_lower and "in use" in error_lower:
            # 提取端口号并换一个
            port_match = re.search(r"-p\s+(\d+):(\d+)", command)
            if port_match:
                host_port = int(port_match.group(1))
                container_port = port_match.group(2)
                new_host_port = host_port + 1
                new_command = re.sub(
                    r"-p\s+\d+:" + container_port,
                    f"-p {new_host_port}:{container_port}",
                    command,
                )
                return {
                    "action": "fix",
                    "thinking": [
                        f"观察：端口 {host_port} 被占用",
                        f"决策：改用端口 {new_host_port}",
                    ],
                    "new_command": new_command,
                    "cause": f"端口 {host_port} 被占用，已改用 {new_host_port}",
                }

        # 容器名称冲突：删除旧容器
        if "container name" in error_lower and "already in use" in error_lower:
            name_match = re.search(r"--name\s+(\S+)", command)
            if name_match:
                container_name = name_match.group(1)
                return {
                    "action": "fix",
                    "thinking": [
                        f"观察：容器 {container_name} 已存在",
                        "决策：先删除旧容器再创建",
                    ],
                    "commands": [f"docker rm -f {container_name}"],
                    "cause": f"容器 {container_name} 已存在，已删除旧容器",
                }

        return None

    async def _llm_diagnose_error(
        self,
        command: str,
        error: str,
        project_type: str,
        project_dir: str,
        known_files: Optional[list[str]] = None,
        collected_info: Optional[str] = None,
    ) -> dict[str, object]:
        """LLM 诊断错误并提供修复方案"""
        # 1. 先尝试本地规则修复（快速、可靠）
        local_fix = self._try_local_fix(command, error)
        if local_fix:
            self._report_progress("deploy", "    🔧 使用本地规则修复...")
            return local_fix

        # 2. 本地无法修复，调用 LLM
        prompt = DIAGNOSE_ERROR_PROMPT.format(
            command=command,
            error=error[:1500],  # 截断错误信息
            project_type=project_type,
            project_dir=project_dir,
            known_files=", ".join(known_files[:30]) if known_files else "(未知)",
            collected_info=collected_info or "(无)",
        )

        self._report_progress("deploy", "    🤖 调用 LLM 分析中...")

        try:
            # 添加超时保护（60秒）
            response = await asyncio.wait_for(
                self._llm.generate(
                    "You are an ops expert. Diagnose and fix. Return only valid JSON.",
                    prompt,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            self._report_progress("deploy", "    ⚠️ LLM 响应超时")
            return {"action": "give_up", "cause": "LLM 响应超时", "suggestion": "请检查网络连接或稍后重试"}
        except Exception as e:
            self._report_progress("deploy", f"    ⚠️ LLM 调用失败: {e}")
            return {"action": "give_up", "cause": f"LLM 调用失败: {e}", "suggestion": "请检查 LLM 配置"}

        parsed = self._llm.parse_json_response(response)
        if not parsed:
            self._report_progress("deploy", "    ⚠️ LLM 返回格式错误")
            # 返回更详细的调试信息
            self._report_progress("deploy", f"    📝 LLM 原始响应: {response[:200]}...")
            return {"action": "give_up", "cause": "无法解析诊断结果", "suggestion": "请手动检查"}

        return parsed

    async def _react_diagnose_loop(
        self,
        command: str,
        error: str,
        project_type: str,
        project_dir: str,
        known_files: list[str],
        confirmation_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        max_iterations: int = 3,
    ) -> tuple[bool, str, list[str], Optional[str]]:
        """ReAct 循环自主诊断和修复

        Returns:
            (fixed, message, fix_commands, new_command)
            - new_command: 如果需要用新命令替换原命令，返回新命令
        """
        collected_info: list[str] = []
        fix_commands: list[str] = []

        for iteration in range(max_iterations):
            self._report_progress("deploy", f"    🔍 AI 诊断中 (轮次 {iteration + 1}/{max_iterations})...")

            # 调用 LLM 诊断
            diagnosis = await self._llm_diagnose_error(
                command=command,
                error=error,
                project_type=project_type,
                project_dir=project_dir,
                known_files=known_files,
                collected_info="\n".join(collected_info) if collected_info else None,
            )

            # 显示思考过程
            thinking = diagnosis.get("thinking", [])
            if isinstance(thinking, list):
                for thought in thinking:
                    self._report_progress("deploy", f"    💭 {thought}")

            action = diagnosis.get("action", "give_up")
            cause = diagnosis.get("cause", "")
            new_command = diagnosis.get("new_command")

            if cause:
                self._report_progress("deploy", f"    💡 分析: {cause}")

            # 根据 action 执行不同操作
            if action == "give_up":
                suggestion = diagnosis.get("suggestion", "请手动检查项目")
                return False, f"原因: {cause}\n建议: {suggestion}", [], None

            elif action == "fix":
                # 检查是否有新命令（替换原命令）
                if isinstance(new_command, str) and new_command:
                    self._report_progress("deploy", f"    🔄 使用修改后的命令:")
                    self._report_progress("deploy", f"    📝 {new_command[:100]}...")
                    return True, f"已生成修复命令", [], new_command

                # 执行修复命令
                commands = diagnosis.get("commands", [])
                if isinstance(commands, list):
                    for cmd in commands[:5]:
                        if isinstance(cmd, str) and cmd:
                            # 检查是否需要确认（破坏性操作）
                            if self._is_destructive_command(cmd):
                                if confirmation_callback:
                                    self._report_progress("deploy", f"    ⚠️ 需要确认: {cmd}")
                                    confirmed = await confirmation_callback("执行命令", cmd)
                                    if not confirmed:
                                        collected_info.append(f"用户拒绝执行: {cmd}")
                                        continue
                                else:
                                    collected_info.append(f"跳过破坏性命令（需用户确认）: {cmd}")
                                    continue

                            self._report_progress("deploy", f"    🔧 修复: {cmd}")
                            result = await self._shell.execute(
                                "execute_command",
                                {"command": cmd, "working_dir": project_dir},
                            )
                            if result.success:
                                self._report_progress("deploy", f"    ✓ 成功")
                                fix_commands.append(cmd)
                            else:
                                self._report_progress("deploy", f"    ✗ 失败: {result.message[:100]}")
                                collected_info.append(f"修复命令 `{cmd}` 失败: {result.message[:200]}")

                # 修复后返回，让调用方重试原命令
                if fix_commands:
                    return True, f"已执行修复命令", fix_commands, None

            elif action == "ask_user":
                # 询问用户做决定（如选择端口）
                ask_info = diagnosis.get("ask_user", {})

                if isinstance(ask_info, dict):
                    question = str(ask_info.get("question", "请做出选择"))
                    options = ask_info.get("options", [])
                    context = str(ask_info.get("context", ""))

                    if not isinstance(options, list) or not options:
                        options = ["确认", "取消"]

                    # 确保选项是字符串列表
                    options = [str(opt) for opt in options]

                    self._report_progress("deploy", f"    ❓ {question}")
                    if context:
                        self._report_progress("deploy", f"    📋 {context}")

                    if self._ask_user_callback:
                        # 调用用户选择回调
                        user_choice = await self._ask_user_callback(question, options, context)
                        self._report_progress("deploy", f"    ✓ 用户选择: {user_choice}")
                        collected_info.append(f"用户选择: {user_choice}")

                        # 如果用户取消，终止
                        if not user_choice:
                            return False, "用户取消操作", [], None

                        # 根据用户选择生成新命令（端口替换等）
                        # 将用户选择添加到收集的信息中，下一轮 LLM 会根据选择生成命令
                    else:
                        # 没有用户选择回调，记录并继续
                        collected_info.append(f"需要用户选择但无回调: {question}")
                        self._report_progress("deploy", f"    ⚠️ 无法询问用户，跳过此步骤")

            elif action == "edit_file":
                # 编辑文件：需要用户确认
                edit_info = diagnosis.get("edit_file", {})
                if isinstance(edit_info, dict):
                    file_path = edit_info.get("path", "")
                    content = edit_info.get("content", "")
                    reason = edit_info.get("reason", "")

                    if file_path and content:
                        full_path = os.path.join(project_dir, file_path)

                        if confirmation_callback:
                            self._report_progress("deploy", f"    ✏️ 需要编辑: {file_path}")
                            self._report_progress("deploy", f"    原因: {reason}")
                            confirmed = await confirmation_callback(f"编辑文件 {file_path}", f"原因: {reason}\n内容预览: {content[:200]}...")
                            if confirmed:
                                try:
                                    with open(full_path, "w", encoding="utf-8") as f:
                                        f.write(content)
                                    self._report_progress("deploy", f"    ✓ 文件已更新")
                                    fix_commands.append(f"edit:{file_path}")
                                    return True, f"已编辑文件 {file_path}", fix_commands, None
                                except Exception as e:
                                    collected_info.append(f"编辑文件失败: {e}")
                            else:
                                collected_info.append(f"用户拒绝编辑文件: {file_path}")
                        else:
                            collected_info.append(f"需要编辑文件但无法确认: {file_path}")

            else:
                # 未知 action（包括 explore、diagnose）- 跳过，让 LLM 重新思考
                collected_info.append(f"跳过操作: {action}")
                self._report_progress("deploy", f"    ⚠️ 跳过探索操作，继续分析...")

        # 达到最大迭代次数
        return False, "诊断超过最大尝试次数", [], None

    def _is_safe_read_command(self, cmd: str) -> bool:
        """检查是否是安全的只读命令"""
        safe_prefixes = [
            "ls", "cat", "head", "tail", "grep", "find", "pwd", "echo",
            "docker ps", "docker logs", "docker inspect", "docker images",
            "ps ", "ps aux", "env", "printenv", "which", "whereis",
            "file ", "stat ", "du ", "df ", "free", "uname",
            "python --version", "node --version", "docker --version",
        ]
        cmd_lower = cmd.lower().strip()
        return any(cmd_lower.startswith(prefix) for prefix in safe_prefixes)

    def _is_destructive_command(self, cmd: str) -> bool:
        """检查是否是破坏性命令（需要用户确认）"""
        destructive_patterns = [
            "rm ", "rm -", "rmdir", "delete",
            "kill ", "kill -", "pkill", "killall",
            "sudo ", "chmod ", "chown ",
            "docker rm", "docker rmi", "docker stop", "docker kill",
            "> ", ">> ",  # 重定向覆盖文件
            "mv ", "cp -f",
        ]
        cmd_lower = cmd.lower().strip()
        return any(pattern in cmd_lower for pattern in destructive_patterns)

    async def _read_file_safe(self, file_path: str, max_lines: int = 50) -> str:
        """安全读取文件内容"""
        try:
            if not os.path.exists(file_path):
                return "(文件不存在)"
            if not os.path.isfile(file_path):
                return "(不是文件)"
            if os.path.getsize(file_path) > 100000:  # 100KB 限制
                return "(文件过大，跳过)"

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                content = "".join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (截断，共 {len(lines)} 行)"
                return content
        except Exception as e:
            return f"(读取失败: {e})"

    async def _verify_docker_deployment(
        self,
        deploy_steps: list[dict[str, str]],
        project_dir: str,
        project_type: str,
        known_files: list[str],
        max_fix_attempts: int = 2,
    ) -> tuple[bool, str, Optional[dict[str, str]]]:
        """验证 Docker 部署是否成功
        
        检查容器是否真正运行，如果没有运行则尝试诊断和修复。
        
        Args:
            deploy_steps: 部署步骤列表
            project_dir: 项目目录
            project_type: 项目类型
            known_files: 项目文件列表
            max_fix_attempts: 最大修复尝试次数
        
        Returns:
            (success, message, container_info)
        """
        # 1. 从部署步骤中提取容器名称
        container_name = None
        docker_run_command = None
        
        for step in deploy_steps:
            command = step.get("command", "")
            if "docker run" in command and "--name" in command:
                docker_run_command = command
                name_match = re.search(r"--name\s+(\S+)", command)
                if name_match:
                    container_name = name_match.group(1)
                    break
        
        if not container_name:
            self._report_progress("deploy", "    ℹ️ 未检测到 Docker 容器名称，跳过验证")
            return True, "未检测到容器名称", None
        
        self._report_progress("deploy", f"    🔍 检查容器 {container_name} 状态...")
        
        # 2. 执行 docker ps 检查容器是否运行
        for attempt in range(max_fix_attempts + 1):
            check_result = await self._shell.execute(
                "execute_command",
                {"command": f"docker ps --filter name=^{container_name}$ --format '{{{{.Names}}}} {{{{.Status}}}}'"},
            )
            
            if check_result.success and container_name in check_result.message:
                # 容器正在运行
                status_match = re.search(rf"{container_name}\s+(.+)", check_result.message)
                status = status_match.group(1) if status_match else "running"
                
                # 检查是否健康运行（不是刚启动就退出）
                if "Up" in status:
                    self._report_progress("deploy", f"    ✅ 容器 {container_name} 运行中: {status}")
                    return True, f"✅ 容器验证通过: {container_name} ({status})", {
                        "container_name": container_name,
                        "status": status,
                    }
            
            # 3. 容器没有运行，检查是否退出
            self._report_progress("deploy", f"    ⚠️ 容器 {container_name} 未运行，检查原因...")
            
            # 检查容器是否存在但已退出
            all_containers_result = await self._shell.execute(
                "execute_command",
                {"command": f"docker ps -a --filter name=^{container_name}$ --format '{{{{.Names}}}} {{{{.Status}}}}'"},
            )
            
            container_exists = container_name in all_containers_result.message
            
            if container_exists:
                # 容器存在但已退出，获取日志
                self._report_progress("deploy", f"    📋 获取容器日志...")
                logs_result = await self._shell.execute(
                    "execute_command",
                    {"command": f"docker logs --tail 50 {container_name} 2>&1"},
                )
                container_logs = logs_result.message if logs_result.success else "无法获取日志"
                
                error_message = f"容器 {container_name} 已退出。\n日志:\n{container_logs[:500]}"
            else:
                error_message = f"容器 {container_name} 不存在"
            
            self._report_progress("deploy", f"    ❌ {error_message[:100]}...")
            
            # 4. 如果还有修复尝试次数，启动诊断
            if attempt < max_fix_attempts and docker_run_command:
                self._report_progress("deploy", f"    🔧 尝试修复 (尝试 {attempt + 1}/{max_fix_attempts})...")
                
                # 使用 ReAct 循环诊断
                fixed, diagnose_msg, fix_commands, new_command = await self._react_diagnose_loop(
                    command=docker_run_command,
                    error=error_message,
                    project_type=project_type,
                    project_dir=project_dir,
                    known_files=known_files,
                    confirmation_callback=self._confirmation_callback,
                    max_iterations=2,
                )
                
                if fixed:
                    # 如果有新命令，执行它
                    if new_command:
                        docker_run_command = new_command
                        self._report_progress("deploy", f"    🔄 执行修复后的命令...")
                        run_result = await self._shell.execute(
                            "execute_command",
                            {"command": new_command, "working_dir": project_dir},
                        )
                        if not run_result.success:
                            self._report_progress("deploy", f"    ❌ 修复命令执行失败: {run_result.message[:100]}")
                            continue
                    
                    # 等待容器启动
                    import asyncio
                    await asyncio.sleep(2)
                    continue  # 重新检查容器状态
                else:
                    self._report_progress("deploy", f"    ❌ 无法自动修复: {diagnose_msg[:100]}")
            
            # 修复失败或没有更多尝试次数
            return False, f"容器 {container_name} 启动失败: {error_message[:200]}", None
        
        return False, f"容器 {container_name} 验证失败", None

    async def _execute_with_retry(
        self,
        step: dict[str, str],
        project_dir: str,
        project_type: str,
        known_files: list[str],
        max_retries: int = 3,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """执行命令，失败时使用 ReAct 循环自主诊断并重试

        Returns:
            (success, message)
        """
        command = step.get("command", "")
        description = step.get("description", command)

        if not command:
            return False, "空命令"

        if dry_run:
            return True, f"[DRY-RUN] 将执行: {command}"

        # 保存第一次执行的错误信息
        first_error: str = ""
        current_command = command  # 当前要执行的命令（可能被 AI 修改）

        for attempt in range(max_retries + 1):
            self._report_progress("deploy", f"    执行: {current_command[:80]}...")
            result = await self._shell.execute(
                "execute_command",
                {"command": current_command, "working_dir": project_dir},
            )

            if result.success:
                return True, f"✓ {description}"

            # 保存第一次错误
            if attempt == 0:
                first_error = result.message

            # 最后一次尝试失败
            if attempt == max_retries:
                return False, f"✗ {description}\n命令: {current_command}\n错误: {first_error}"

            # 使用 ReAct 循环自主诊断
            self._report_progress("deploy", f"    ⚠️ 命令失败，启动 AI 自主诊断...")
            fixed, diagnose_msg, fix_commands, new_command = await self._react_diagnose_loop(
                command=current_command,
                error=result.message,
                project_type=project_type,
                project_dir=project_dir,
                known_files=known_files,
                confirmation_callback=self._confirmation_callback,
                max_iterations=3,
            )

            if not fixed:
                # 无法修复
                error_detail = f"✗ {description}\n命令: {current_command}\n错误: {first_error}"
                if diagnose_msg:
                    error_detail += f"\n{diagnose_msg}"
                return False, error_detail

            # 检查是否有新命令（AI 修改了命令，如换端口）
            if new_command:
                current_command = new_command
                self._report_progress("deploy", f"    🔄 使用修改后的命令重试...")
            elif fix_commands:
                self._report_progress("deploy", f"    ✓ 修复完成，重试原命令...")

            # 继续下一次循环重试

        return False, f"✗ {description}: 重试次数耗尽\n命令: {current_command}\n错误: {first_error}"

    async def _intelligent_deploy(self, args: dict[str, ArgValue]) -> WorkerResult:
        """LLM 驱动的智能部署

        流程：
        1. 收集项目信息（README、文件列表）
        2. 收集本机环境信息
        3. LLM 分析并生成部署计划
        4. 逐步执行，遇错自我修复
        """
        repo_url = args.get("repo_url")
        if not isinstance(repo_url, str):
            return WorkerResult(
                success=False,
                message="repo_url parameter is required",
            )

        target_dir = args.get("target_dir", "~/projects")
        if not isinstance(target_dir, str):
            target_dir = "~/projects"

        dry_run = args.get("dry_run", False)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() == "true"

        steps_log: list[str] = []

        # ========== Step 1: 分析项目 ==========
        self._report_progress("deploy", "📋 Step 1/4: 收集项目信息...")
        steps_log.append("📋 Step 1/4: 收集项目信息...")

        parsed = self._parse_github_url(repo_url)
        if not parsed:
            return WorkerResult(
                success=False,
                message=f"无效的 GitHub URL: {repo_url}",
            )

        owner, repo = parsed

        # 获取 README
        self._report_progress("deploy", "  获取 README...")
        readme_result = await self._http.execute(
            "fetch_github_readme",
            {"repo_url": repo_url},
        )
        readme_content = ""
        if readme_result.success and readme_result.data:
            readme_content = str(readme_result.data.get("content", ""))

        # 获取文件列表
        self._report_progress("deploy", "  获取文件列表...")
        files_result = await self._http.execute(
            "list_github_files",
            {"repo_url": repo_url},
        )
        key_files: list[str] = []
        if files_result.success and files_result.data:
            key_files_str = files_result.data.get("key_files", "")
            if isinstance(key_files_str, str) and key_files_str:
                key_files = [f.strip() for f in key_files_str.split(",")]

        steps_log.append(f"  ✓ 仓库: {owner}/{repo}")
        steps_log.append(f"  ✓ 关键文件: {', '.join(key_files[:10]) if key_files else '无'}")

        # ========== Step 2: 克隆仓库 ==========
        self._report_progress("deploy", "📦 Step 2/4: 克隆仓库...")
        steps_log.append("📦 Step 2/4: 克隆仓库...")

        target_dir = os.path.expanduser(target_dir)
        clone_path = os.path.join(target_dir, repo)
        safe_target_dir = shlex.quote(target_dir)
        safe_clone_path = shlex.quote(clone_path)
        safe_repo_url = shlex.quote(repo_url)

        if dry_run:
            steps_log.append(f"  [DRY-RUN] 将执行: mkdir -p {target_dir}")
            steps_log.append(f"  [DRY-RUN] 将执行: git clone {repo_url}")
        else:
            # 创建目标目录
            mkdir_result = await self._shell.execute(
                "execute_command",
                {"command": f"mkdir -p {safe_target_dir}"},
            )
            if not mkdir_result.success:
                return WorkerResult(
                    success=False,
                    message=f"创建目录失败: {mkdir_result.message}",
                )

            # 检查是否已存在
            check_result = await self._shell.execute(
                "execute_command",
                {"command": f"test -d {safe_clone_path} && echo 'EXISTS' || echo 'NOT_EXISTS'"},
            )
            already_exists = False
            if check_result.success and check_result.data:
                stdout = check_result.data.get("stdout", "")
                if isinstance(stdout, str) and "EXISTS" in stdout and "NOT" not in stdout:
                    already_exists = True
                    steps_log.append(f"  ⚠️ 项目已存在: {clone_path}")

            if not already_exists:
                clone_result = await self._shell.execute(
                    "execute_command",
                    {"command": f"git clone {safe_repo_url} {safe_clone_path}"},
                )
                if not clone_result.success:
                    return WorkerResult(
                        success=False,
                        message=f"克隆失败: {clone_result.message}",
                    )
                steps_log.append(f"  ✓ 克隆完成: {clone_path}")

        # ========== Step 3: LLM 生成部署计划 ==========
        self._report_progress("deploy", "🤖 Step 3/4: AI 分析项目并生成部署计划...")
        steps_log.append("🤖 Step 3/4: AI 分析项目并生成部署计划...")

        self._report_progress("deploy", "  收集本机环境信息...")
        env_info = await self._collect_env_info()
        self._report_progress("deploy", "  调用 LLM 生成部署计划...")
        deploy_steps, project_type, notes, thinking = await self._llm_generate_plan(
            readme=readme_content,
            files=key_files,
            env_info=env_info,
            project_dir=clone_path,  # 传入项目目录，让 LLM 读取本地文件
        )

        if not deploy_steps:
            return WorkerResult(
                success=False,
                message="无法生成部署计划。请检查项目结构或手动部署。",
            )

        # 展示 LLM 思考过程
        if thinking:
            steps_log.append("  💭 AI 思考过程:")
            for i, thought in enumerate(thinking, 1):
                thought_str = str(thought)
                self._report_progress("deploy", f"    💭 {thought_str}")
                steps_log.append(f"    {i}. {thought_str}")

        steps_log.append(f"  ✓ 项目类型: {project_type}")
        steps_log.append(f"  ✓ 部署步骤: {len(deploy_steps)} 步")
        if notes:
            steps_log.append(f"  📝 备注: {notes}")

        # ========== Step 4: 执行部署计划 ==========
        self._report_progress("deploy", "🚀 Step 4/4: 执行部署计划...")
        steps_log.append("🚀 Step 4/4: 执行部署计划...")

        failed_step: Optional[str] = None
        for i, step in enumerate(deploy_steps, 1):
            description = step.get("description", step.get("command", ""))
            self._report_progress("deploy", f"  [{i}/{len(deploy_steps)}] {description}")
            steps_log.append(f"  [{i}/{len(deploy_steps)}] {description}")

            success, message = await self._execute_with_retry(
                step=step,
                project_dir=clone_path,
                project_type=project_type,
                known_files=key_files,
                dry_run=dry_run,
            )

            if not success:
                failed_step = message
                steps_log.append(f"    ❌ {message}")
                break
            else:
                steps_log.append(f"    {message}")

        # ========== 结果汇总 ==========
        summary = "\n".join(steps_log)

        if failed_step:
            summary += f"\n\n❌ 部署失败: {failed_step}"
            summary += "\n\n💡 可能的解决方法:"
            summary += "\n1. 检查项目 README 了解具体要求"
            summary += "\n2. 手动进入项目目录排查问题"
            summary += f"\n   cd {clone_path}"
            return WorkerResult(
                success=False,
                data=cast(
                    dict[str, Union[str, int, bool]],
                    {
                        "project_dir": clone_path,
                        "project_type": project_type,
                        "repo_url": repo_url,
                    },
                ),
                message=summary,
                task_completed=True,
                simulated=bool(dry_run),
            )

        # ========== Step 5: 验证部署（Docker 项目）==========
        if project_type == "docker" and not dry_run:
            self._report_progress("deploy", "\n🔍 Step 5/5: 验证部署...")
            verify_success, verify_message, container_info = await self._verify_docker_deployment(
                deploy_steps=deploy_steps,
                project_dir=clone_path,
                project_type=project_type,
                known_files=key_files,
            )
            
            if not verify_success:
                summary += f"\n\n⚠️ 部署验证失败: {verify_message}"
                summary += "\n\n💡 可能的解决方法:"
                summary += "\n1. 检查 docker logs 查看容器日志"
                summary += "\n2. 确认端口没有被占用"
                summary += f"\n3. 手动进入项目目录排查问题: cd {clone_path}"
                return WorkerResult(
                    success=False,
                    data=cast(
                        dict[str, Union[str, int, bool]],
                        {
                            "project_dir": clone_path,
                            "project_type": project_type,
                            "repo_url": repo_url,
                        },
                    ),
                    message=summary,
                    task_completed=True,
                    simulated=bool(dry_run),
                )
            
            # 验证成功，添加容器信息
            if container_info:
                summary += f"\n\n{verify_message}"

        summary += "\n\n✅ 部署完成！"
        summary += f"\n📂 项目路径: {clone_path}"
        summary += f"\n🎯 项目类型: {project_type}"

        if dry_run:
            summary = "[DRY-RUN 模式]\n\n" + summary

        return WorkerResult(
            success=True,
            data=cast(
                dict[str, Union[str, int, bool]],
                {
                    "project_dir": clone_path,
                    "project_type": project_type,
                    "repo_url": repo_url,
                },
            ),
            message=summary,
            task_completed=True,
            simulated=bool(dry_run),
        )
