#!/usr/bin/env python3
"""OpsAI 本地安装脚本。

使用方式：
1. git clone 后进入仓库目录
2. 运行: python install.py
3. 之后可在任意目录直接执行: opsai
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import venv
from pathlib import Path

MIN_PYTHON = (3, 9)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安装 OpsAI 到当前用户环境")
    parser.add_argument(
        "--install-home",
        default="~/.opsai",
        help="安装目录（默认：~/.opsai）",
    )
    parser.add_argument(
        "--bin-dir",
        default="~/.local/bin",
        help="命令链接目录（默认：~/.local/bin）",
    )
    parser.add_argument(
        "--skip-pip-upgrade",
        action="store_true",
        help="跳过 pip 升级步骤",
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="强制重装 Python 包",
    )
    parser.add_argument(
        "--recreate-venv",
        action="store_true",
        help="重建虚拟环境（会删除原有 venv）",
    )
    return parser.parse_args()


def run_command(cmd: list[str]) -> None:
    print(f"→ 执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def assert_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        current = ".".join(str(x) for x in sys.version_info[:3])
        required = ".".join(str(x) for x in MIN_PYTHON)
        raise RuntimeError(f"Python 版本过低: {current}，需要 >= {required}")


def get_venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def get_venv_entry(venv_dir: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def ensure_repo_root(repo_root: Path) -> None:
    if not (repo_root / "pyproject.toml").exists():
        raise RuntimeError(f"未找到 pyproject.toml，请在仓库根目录执行：{repo_root}")


def create_venv(venv_dir: Path, recreate: bool) -> None:
    if recreate and venv_dir.exists():
        print(f"→ 删除旧虚拟环境: {venv_dir}")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        print(f"→ 创建虚拟环境: {venv_dir}")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    else:
        print(f"→ 复用已有虚拟环境: {venv_dir}")


def install_package(
    venv_python: Path,
    repo_root: Path,
    skip_pip_upgrade: bool,
    force_reinstall: bool,
) -> None:
    if not skip_pip_upgrade:
        run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])

    cmd = [str(venv_python), "-m", "pip", "install"]
    if force_reinstall:
        cmd.append("--force-reinstall")
    cmd.append(str(repo_root))
    run_command(cmd)


def write_launcher(launcher_path: Path, target_cmd: Path) -> None:
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "#!/usr/bin/env sh\n"
        f'exec "{target_cmd}" "$@"\n'
    )
    launcher_path.write_text(content, encoding="utf-8")
    mode = launcher_path.stat().st_mode
    launcher_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_launchers(bin_dir: Path, venv_dir: Path) -> None:
    for name in ("opsai", "opsai-tui"):
        target = get_venv_entry(venv_dir, name)
        if not target.exists():
            raise RuntimeError(f"安装后未找到命令: {target}")
        launcher = bin_dir / name
        write_launcher(launcher, target)
        print(f"✓ 已写入命令: {launcher} -> {target}")


def print_path_hint(bin_dir: Path) -> None:
    path_items = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) in path_items:
        print(f"✓ PATH 已包含: {bin_dir}")
        return

    print("")
    print("⚠️ 当前 PATH 未包含命令目录，请执行以下任一命令后重新登录 shell：")
    print(f'  echo \'export PATH="{bin_dir}:$PATH"\' >> ~/.zshrc')
    print(f'  echo \'export PATH="{bin_dir}:$PATH"\' >> ~/.bashrc')


def verify_install(bin_dir: Path) -> None:
    opsai_path = bin_dir / "opsai"
    if not opsai_path.exists():
        raise RuntimeError(f"安装校验失败，未找到: {opsai_path}")

    completed = subprocess.run(
        [str(opsai_path), "--version"],
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        output = completed.stdout.strip() or completed.stderr.strip()
        print(f"✓ 安装校验通过: {output}")
    else:
        print("⚠️ 安装完成，但版本校验失败。请手动执行 `opsai --help` 检查。")


def main() -> None:
    args = parse_args()
    assert_python_version()

    repo_root = Path(__file__).resolve().parent
    ensure_repo_root(repo_root)

    install_home = Path(args.install_home).expanduser().resolve()
    bin_dir = Path(args.bin_dir).expanduser().resolve()
    venv_dir = install_home / "venv"

    print("开始安装 OpsAI...")
    print(f"仓库目录: {repo_root}")
    print(f"安装目录: {install_home}")
    print(f"命令目录: {bin_dir}")
    print("")

    create_venv(venv_dir, recreate=args.recreate_venv)
    venv_python = get_venv_python(venv_dir)
    if not venv_python.exists():
        raise RuntimeError(f"虚拟环境 Python 不存在: {venv_python}")

    install_package(
        venv_python=venv_python,
        repo_root=repo_root,
        skip_pip_upgrade=args.skip_pip_upgrade,
        force_reinstall=args.force_reinstall,
    )
    ensure_launchers(bin_dir, venv_dir)
    verify_install(bin_dir)
    print_path_hint(bin_dir)

    print("")
    print("安装完成。你现在可以执行：")
    print("  opsai --help")
    print("  opsai-tui")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 命令执行失败，退出码: {e.returncode}", file=sys.stderr)
        sys.exit(e.returncode)
    except Exception as e:
        print(f"\n❌ 安装失败: {e}", file=sys.stderr)
        sys.exit(1)
