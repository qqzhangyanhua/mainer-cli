"""Worker 注册与插件加载"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional

from src.config.manager import WorkersConfig
from src.workers.base import BaseWorker


class WorkerRegistry:
    """Worker 注册中心"""

    def __init__(self, config: WorkersConfig) -> None:
        self._config = config
        self._workers: dict[str, BaseWorker] = {}
        self._errors: list[str] = []

    @property
    def workers(self) -> dict[str, BaseWorker]:
        return self._workers

    def get_errors(self) -> list[str]:
        return list(self._errors)

    def register(self, worker: BaseWorker) -> None:
        """注册 Worker"""
        if not self._config.is_enabled(worker.name):
            return
        self._workers[worker.name] = worker

    def register_factory(self, name: str, factory: Callable[[], BaseWorker]) -> None:
        """按需注册 Worker"""
        if not self._config.is_enabled(name):
            return
        try:
            worker = factory()
            self.register(worker)
        except Exception as exc:
            self._errors.append(f"{name}: {exc}")

    def load_plugins(self) -> None:
        """加载自定义插件"""
        for path_str in self._config.plugin_paths:
            self._load_plugin(Path(path_str).expanduser())

    def _load_plugin(self, path: Path) -> None:
        if not path.exists():
            self._errors.append(f"plugin not found: {path}")
            return

        module = self._load_module_from_path(path)
        if module is None:
            return

        register_func = getattr(module, "register_workers", None)
        if callable(register_func):
            try:
                result = register_func()
                if isinstance(result, list):
                    for worker in result:
                        if isinstance(worker, BaseWorker):
                            self.register(worker)
                return
            except Exception as exc:
                self._errors.append(f"plugin {path}: {exc}")
                return

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BaseWorker) or obj is BaseWorker:
                continue
            if not self._can_instantiate(obj):
                continue
            try:
                worker = obj()
                if isinstance(worker, BaseWorker):
                    self.register(worker)
            except Exception as exc:
                self._errors.append(f"plugin {path}: {exc}")

    @staticmethod
    def _load_module_from_path(path: Path) -> Optional[ModuleType]:
        module_name = f"opsai_plugin_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            return None
        return module

    @staticmethod
    def _can_instantiate(cls: type[BaseWorker]) -> bool:
        try:
            signature = inspect.signature(cls.__init__)
        except (TypeError, ValueError):
            return False
        for name, param in signature.parameters.items():
            if name == "self":
                continue
            if param.default is inspect.Parameter.empty and param.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }:
                return False
        return True
