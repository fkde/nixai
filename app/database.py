from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any

import app.db as _db_package


_MISSING = object()


def _iter_db_modules() -> list[ModuleType]:
    return [
        importlib.import_module(f"{_db_package.__name__}.{module_info.name}")
        for module_info in sorted(pkgutil.iter_modules(_db_package.__path__), key=lambda item: item.name)
        if not module_info.ispkg
    ]


def _is_exported_symbol(module: ModuleType, name: str, value: Any) -> bool:
    if name.startswith("_"):
        return False
    if getattr(value, "__module__", None) == module.__name__:
        return True
    return name.isupper()


def _re_export_db_symbols() -> list[str]:
    exported: dict[str, Any] = {}
    for module in _iter_db_modules():
        for name, value in vars(module).items():
            if not _is_exported_symbol(module, name, value):
                continue
            existing = exported.get(name, _MISSING)
            if existing is not _MISSING and existing is not value:
                raise RuntimeError(f"Duplicate database export: {name}")
            exported[name] = value
    globals().update(exported)
    return sorted(exported)


__all__ = _re_export_db_symbols()
