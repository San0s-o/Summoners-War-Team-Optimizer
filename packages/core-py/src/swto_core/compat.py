from __future__ import annotations

from importlib import import_module
from types import ModuleType


def get_importer_module() -> ModuleType:
    """Compatibility bridge to existing importer until migration is complete."""
    return import_module("app.importer.sw_json_importer")


def get_engine_modules() -> dict[str, ModuleType]:
    """Compatibility bridge to existing engine modules."""
    return {
        "global_optimizer": import_module("app.engine.global_optimizer"),
        "greedy_optimizer": import_module("app.engine.greedy_optimizer"),
        "arena_rush_optimizer": import_module("app.engine.arena_rush_optimizer"),
    }
