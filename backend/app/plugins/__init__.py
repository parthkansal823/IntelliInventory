"""Drop-in plugins (Hermes-style `register(ctx)`).

Any ``*.py`` module in this package - or in ``PLUGINS_DIR`` - that defines
``register(ctx)`` is loaded at startup. The context lets a plugin add:

* agent lifecycle hooks  - ``ctx.register_hook("pre_tool_call", fn)``
* event hooks            - ``ctx.on_event("po.*", fn)``
* agent/MCP tools        - ``ctx.register_tool(fn, requires_approval=False)``
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agents.hooks import AgentHook, agent_hooks
from app.agents.toolkit import tools
from app.hooks.bus import EventHook, bus

log = logging.getLogger("intelliinventory.plugins")
LOADED: list[dict] = []


class PluginContext:
    def __init__(self, name: str) -> None:
        self.name = name
        self.registered: list[str] = []

    def register_hook(
        self, event: str, fn: Callable[..., Any], *, name: str | None = None, description: str = "", priority: int = 100
    ) -> None:
        hook_name = name or f"{self.name}.{fn.__name__}"
        agent_hooks.register(
            AgentHook(hook_name, event, fn, description or (fn.__doc__ or "").strip().split("\n")[0], priority, builtin=False)
        )
        self.registered.append(f"agent-hook:{hook_name}")

    def on_event(
        self, pattern: str, fn: Callable[..., Any], *, name: str | None = None, description: str = "", priority: int = 100
    ) -> None:
        hook_name = name or f"{self.name}.{fn.__name__}"
        bus.register(
            EventHook(hook_name, pattern, fn, description or (fn.__doc__ or "").strip().split("\n")[0], priority, builtin=False)
        )
        self.registered.append(f"event-hook:{hook_name}")

    def register_tool(
        self, fn: Callable[..., Any], *, requires_approval: bool = False, mutates: bool = False, tags: tuple[str, ...] = ()
    ) -> None:
        tool = tools.add(fn, requires_approval=requires_approval, mutates=mutates or requires_approval, tags=("plugin", *tags))
        self.registered.append(f"tool:{tool.name}")


def _load_module(module: Any, source: str) -> None:
    register = getattr(module, "register", None)
    if not callable(register):
        return
    ctx = PluginContext(getattr(module, "PLUGIN_NAME", module.__name__.rsplit(".", 1)[-1]))
    try:
        register(ctx)
        LOADED.append(
            {
                "name": ctx.name,
                "source": source,
                "registered": ctx.registered,
                "description": (module.__doc__ or "").strip().split("\n")[0],
            }
        )
        log.info("plugin %s loaded: %s", ctx.name, ", ".join(ctx.registered))
    except Exception:  # noqa: BLE001
        log.exception("plugin %s failed to register", ctx.name)


def load_plugins(extra_dir: Path | None = None) -> list[dict]:
    LOADED.clear()
    for info in pkgutil.iter_modules(__path__):
        _load_module(importlib.import_module(f"{__name__}.{info.name}"), "builtin")
    if extra_dir and Path(extra_dir).is_dir():
        for path in sorted(Path(extra_dir).glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"ii_plugin_{path.stem}", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _load_module(module, str(path))
    return LOADED
