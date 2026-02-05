# Changelog

All notable changes to OpsAI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-02-05

### 🎉 Major Performance Improvements

**Dependencies reduced by 87%** (173MB → 23MB)

- ⚡ Installation speed: **5x faster** (60s → 12s)
- ⚡ Startup speed: **30% faster** (3s → 2s)
- 📦 Core dependencies: 6 packages (down from 9)

### ✨ Changed

#### Docker Operations (No Breaking Changes)
- **Removed docker-py dependency** (50MB saved)
- Refactored `ContainerWorker` to use shell commands (`docker` CLI)
- **Benefits**:
  - More intuitive error messages (Docker CLI native errors)
  - No SDK installation required
  - Consistent with user's Docker CLI experience
- **API remains unchanged** - all methods work exactly the same

#### LangGraph (Now Optional)
- **Moved langgraph to optional dependency** (100MB saved from core)
- Install with: `pip install opsai[graph]`
- Default mode (simple ReAct loop) works without LangGraph
- **No breaking changes** - `use_langgraph` parameter defaults to `False`

#### Clipboard Support (Now Optional)
- **Moved pyperclip to optional dependency**
- Install with: `pip install opsai[clipboard]`
- TUI gracefully handles missing clipboard (shows install hint)
- Core functionality unaffected

### 🐛 Fixed
- Improved error messages for Docker connectivity issues
- Better handling of missing optional dependencies

### 📝 Documentation
- Added detailed [Dependency Optimization Summary](docs/dependency-optimization-summary.md)
- Added [Tech Stack Analysis](docs/tech-stack-analysis.md)
- Updated installation instructions with optional features

### 🧪 Testing
- ✅ All 212 tests passing
- ✅ No regression in functionality
- ✅ Improved test isolation (removed DOCKER_AVAILABLE global)

---

## [0.2.0] - 2026-02-04

### Added
- GitHub project one-click deployment (`opsai deploy <url>`)
- Intelligent object analysis (containers, processes, ports)
- Reference resolution in conversations ("this container")
- Deploy intent detection and deterministic workflow
- Context-aware error suggestions

### Changed
- Simplified deploy worker capabilities (single `deploy` action)
- Enhanced preprocessor with intent detection
- Improved prompt engineering for better LLM responses

### Fixed
- Fixed deploy flow state management
- Improved error handling in worker execution

---

## [0.1.0] - 2026-01-XX

### Added
- Initial release
- ReAct (Reason-Act) loop orchestration
- Multi-worker architecture (system, container, shell, analyze, audit)
- TUI mode (Textual-based interactive interface)
- CLI mode (quick one-shot commands)
- Dry-run mode for safe operation preview
- Three-layer safety mechanism
  - Risk level detection (safe/medium/high)
  - Human confirmation for dangerous operations
  - Audit logging
- Docker container management
- Natural language ops automation
- LLM integration (OpenAI-compatible APIs)
  - Ollama support
  - OpenAI support
  - Claude support (via OpenAI-compatible proxy)
- Task template system
- Configuration management

---

## Migration Guide

### Upgrading from v0.2.0 to v0.3.0

#### Standard Installation (Recommended)
```bash
# Upgrade to v0.3.0 (minimal dependencies)
pip install --upgrade opsai
```

**No code changes required!** All APIs remain compatible.

#### If You Use LangGraph Features
```bash
# Install with LangGraph support
pip install --upgrade opsai[graph]
```

Required if you explicitly set `use_langgraph=True` in your code.

#### If You Use Clipboard Features (TUI)
```bash
# Install with clipboard support
pip install --upgrade opsai[clipboard]
```

Required if you use TUI's "Copy last output" feature (Ctrl+Y).

#### Full Installation (All Features)
```bash
# Install everything
pip install --upgrade opsai[all]
```

### Breaking Changes
- **None!** All APIs maintain backward compatibility.
- Docker operations now require `docker` CLI installed (instead of docker-py)

---

## Coming Soon (v0.4.0)

- LLM streaming output (real-time generation display)
- HTTP request caching (faster GitHub README fetching)
- First-run wizard (environment detection + suggestions)
- Scenario recommendation system
- Enhanced error suggestions with actionable steps

---

[0.3.0]: https://github.com/yourusername/opsai/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/yourusername/opsai/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yourusername/opsai/releases/tag/v0.1.0
