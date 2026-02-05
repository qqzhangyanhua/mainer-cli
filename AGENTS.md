# Repository Guidelines

## 项目结构与模块组织
- 源码位于 `src/`，包含 `cli.py`（CLI 入口）、`tui.py`（TUI 入口）、`orchestrator/`（编排与安全）、`workers/`（执行器）、`templates/`（任务模板）、`config/`、`context/`、`llm/`。
- 测试位于 `tests/`，以 `test_*.py` 命名。
- 设计与说明文档见 `README.md`、`design.md`、`docs/`。

## 构建、测试与开发命令
- `uv sync`：安装/同步依赖（开发环境建议先执行）。
- `uv run pytest`：运行全部测试。
- `uv run mypy src/`：严格类型检查（项目启用 `mypy` 严格模式）。
- `uv run ruff format src/ tests/`：格式化代码。
- `uv run opsai query "..."`：在本地以 CLI 方式运行（示例，需先安装依赖）。

## 编码风格与命名规范
- Python 版本 3.9+，Ruff 行宽 100。
- 命名：函数/变量使用 `snake_case`，类使用 `CamelCase`，常量使用 `UPPER_SNAKE_CASE`。
- 类型标注必需，遵循 `mypy` 严格检查与 `pydantic` 插件规则。

## 测试指南
- 测试框架为 `pytest` + `pytest-asyncio`，测试目录固定为 `tests/`。
- 测试文件命名 `test_*.py`，测试函数命名 `test_*`。
- 如需覆盖率，可使用 `uv run pytest --cov`（按需开启）。

## 提交与 Pull Request 规范
- 提交信息采用简洁的约定式格式，例如：`feat: 添加容器分析能力`、`docs: 更新使用说明`、`test: 增加集成测试`。
- PR 需包含：变更摘要、测试结果（命令与结论）、关联问题/需求编号；如影响交互界面或 TUI，附截图或录屏说明。

## 安全与配置提示
- 本项目对危险操作有安全分级（见 `README.md`），开发时不要绕过安全检查。
- 本地配置位于 `~/.opsai/config.json`，请勿在仓库内提交真实 API Key。
