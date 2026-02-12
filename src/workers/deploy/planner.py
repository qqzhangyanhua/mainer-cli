"""Deploy Worker - 信息收集与部署规划"""

from __future__ import annotations

import os
import platform

from src.llm.client import LLMClient
from src.workers.deploy.types import DEPLOY_PLAN_PROMPT
from src.workers.shell import ShellWorker

# 回调类型复用
from src.workers.deploy.types import ProgressCallback


class DeployPlanner:
    """部署规划器：收集环境信息、读取项目文件、生成部署计划"""

    def __init__(
        self,
        shell: ShellWorker,
        llm: LLMClient,
        progress_callback: ProgressCallback = None,
    ) -> None:
        self._shell = shell
        self._llm = llm
        self._progress_callback = progress_callback

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback

    def _report_progress(self, step: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(step, message)

    async def collect_env_info(self) -> dict[str, str]:
        """收集本机环境信息"""
        env_info: dict[str, str] = {
            "os": "unknown",
            "python": "unknown",
            "docker": "not installed",
            "docker_running": "no",
            "node": "not installed",
            "uv": "not installed",
        }

        env_info["os"] = f"{platform.system()} {platform.release()}"

        python_result = await self._shell.execute(
            "execute_command",
            {"command": "which python3"},
        )
        if python_result.success and python_result.data:
            stdout = python_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["python"] = f"python3 ({stdout.strip()})"

        docker_result = await self._shell.execute(
            "execute_command",
            {"command": "docker version"},
        )
        if docker_result.success and docker_result.data:
            stdout = docker_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["docker"] = stdout.strip().splitlines()[0]

                docker_info_result = await self._shell.execute(
                    "execute_command",
                    {"command": "docker info"},
                )
                if docker_info_result.success:
                    env_info["docker_running"] = "yes"
                else:
                    env_info["docker_running"] = "no (Docker daemon not running)"

        node_result = await self._shell.execute(
            "execute_command",
            {"command": "which node"},
        )
        if node_result.success and node_result.data:
            stdout = node_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["node"] = f"installed ({stdout.strip()})"

        uv_result = await self._shell.execute(
            "execute_command",
            {"command": "which uv"},
        )
        if uv_result.success and uv_result.data:
            stdout = uv_result.data.get("stdout", "")
            if isinstance(stdout, str) and stdout.strip():
                env_info["uv"] = f"installed ({stdout.strip()})"

        return env_info

    async def read_local_file(
        self, project_dir: str, filename: str, max_lines: int = 100
    ) -> str:
        """安全读取本地文件内容"""
        file_path = os.path.join(project_dir, filename)
        try:
            if not os.path.exists(file_path):
                return ""
            if not os.path.isfile(file_path):
                return ""
            if os.path.getsize(file_path) > 50000:
                return "(文件过大，跳过)"

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                content = "".join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (截断，仅显示前 {max_lines} 行)"
                return content
        except Exception as e:
            return f"(读取失败: {e})"

    async def collect_key_file_contents(
        self, project_dir: str, key_files: list[str]
    ) -> str:
        """收集关键配置文件的内容"""
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
        max_files = 5

        for filename in priority_files:
            if files_read >= max_files:
                break
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                content = await self.read_local_file(project_dir, filename)
                if content and not content.startswith("("):
                    contents.append(f"=== {filename} ===\n{content}")
                    files_read += 1

        if not contents:
            return "(无关键配置文件)"

        return "\n\n".join(contents)

    async def generate_plan(
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
        readme_truncated = readme[:3000] if readme else "(无 README)"
        files_str = ", ".join(files[:50]) if files else "(无文件列表)"
        env_str = "\n".join(f"- {k}: {v}" for k, v in env_info.items())

        key_file_contents = "(项目尚未克隆)"
        if project_dir:
            self._report_progress("deploy", "  读取本地配置文件...")
            key_file_contents = await self.collect_key_file_contents(project_dir, files)
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

        thinking = parsed.get("thinking", [])
        if not isinstance(thinking, list):
            thinking = []

        steps = parsed.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        project_type = str(parsed.get("project_type", "unknown"))
        notes = str(parsed.get("notes", ""))

        return steps, project_type, notes, thinking
