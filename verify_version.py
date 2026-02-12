#!/usr/bin/env python3
"""验证当前运行的 opsai 代码位置"""
import sys
from pathlib import Path

print(f"Python 解释器: {sys.executable}")
print(f"sys.path (前3个):")
for p in sys.path[:3]:
    print(f"  {p}")

try:
    import src
    src_location = Path(src.__file__).parent
    print(f"\n✓ src 模块位置: {src_location}")
    print(f"  是否在项目目录: {str(src_location).startswith('/Users/zhangyanhua/AI/mainer-cli')}")
except ImportError:
    print("\n✗ 未找到 src 模块")
