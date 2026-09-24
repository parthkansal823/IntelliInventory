"""In-process event bus with pluggable hooks.

Every state change in the system is published as a domain event
(`stock.changed`, `po.created`, `agent.tool_called`, ...). Hooks subscribe to
events with glob patterns (`stock.*`, `*`) and can be sync or async. The bus
is safe to call from worker threads (FastAPI runs sync endpoints and agent
tools in a threadpool): async hooks and live-feed fan-out are marshalled onto
the main event loop.

Hook failures are logged and isolated - a broken hook never breaks the
operation that emitted the event.
"""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("intelliinventory.hooks")


@dataclass
class Event:
    type: str
    payload: dict[str, Any]
    source: str = "system"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventHook:
    name: str
    pattern: str
    handler: Callable[[Event], Any]
    description: str = ""
    priority: int = 100
    builtin: bool = True

    @property
    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.handler)

    def matches(self, event_type: str) -> bool:
        # `|` separates alternatives: "stock.low|stock.out"
        return any(fnmatch.fnmatchcase(event_type, p.strip()) for p in self.pattern.split("|"))


class Toggles:
    """Enable/disable state for every hook (event + agent), persisted in `Setting`."""

    KEY = "hooks.disabled"

    def __init__(self) -> None:
        self._disabled: set[str] = set()

    def load(self) -> None:
        from app.services.settings import get_setting

        self._disabled = set(get_setting(self.KEY, []) or [])

    def is_enabled(self, name: str) -> bool:
        return name not in self._disabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        from app.services.settings import set_setting

        (self._disabled.discard if enabled else self._disabled.add)(name)
        set_setting(self.KEY, sorted(self._disabled))


toggles = Toggles()


class EventBus:
    def __init__(self) -> None:
        self._hooks: list[EventHook] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._pending: set[asyncio.Future[Any]] = set()

    # -- registration -------------------------------------------------------

    def on(
        self, pattern: str, *, name: str | None = None, description: str = "", priority: int = 100, builtin: bool = True
    ) -> Callable[[Callable[[Event], Any]], Callable[[Event], Any]]:
        def decorator(fn: Callable[[Event], Any]) -> Callable[[Event], Any]:
            self.register(
                EventHook(
                    name=name or fn.__name__,
                    pattern=pattern,
                    handler=fn,
                    description=description or (inspect.getdoc(fn) or "").split("\n")[0],
                    priority=priority,
                    builtin=builtin,
                )
            )
            return fn

        return decorator

    def register(self, hook: EventHook) -> None:
        self._hooks = [h for h in self._hooks if h.name != hook.name]
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)

    @property
    def hooks(self) -> list[EventHook]:
        return list(self._hooks)

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    # -- publishing ---------------------------------------------------------

    def emit(self, type: str, payload: dict[str, Any] | None = None, source: str = "system") -> Event:
        """Publish an event. Safe to call from any thread."""
        event = Event(type=type, payload=payload or {}, source=source)
        for hook in self._hooks:
            if not hook.matches(type) or not toggles.is_enabled(hook.name):
                continue
            if hook.is_async:
                self._schedule(self._run_async_hook(hook, event))
            else:
                try:
                    hook.handler(event)
                except Exception:  # noqa: BLE001 - hooks must never break the caller
                    log.exception("event hook %s failed on %s", hook.name, type)
        self._broadcast(event)
        return event

    async def _run_async_hook(self, hook: EventHook, event: Event) -> None:
        try:
            await hook.handler(event)
        except Exception:  # noqa: BLE001
            log.exception("async event hook %s failed on %s", hook.name, event.type)

    def _on_loop_thread(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    def _schedule(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        if self._on_loop_thread():
            task = loop.create_task(coro)
        else:
            task = asyncio.run_coroutine_threadsafe(coro, loop)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def _broadcast(self, event: Event) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or not self._subscribers:
            return
        for queue in list(self._subscribers):
            if self._on_loop_thread():
                _put_nowait(queue, event)
            else:
                loop.call_soon_threadsafe(_put_nowait, queue, event)

    async def drain(self) -> None:
        """Wait for in-flight async hooks (used by tests and shutdown)."""
        while self._pending:
            pending = [p if isinstance(p, asyncio.Future) else asyncio.wrap_future(p) for p in self._pending]
            await asyncio.gather(*pending, return_exceptions=True)

    # -- live feed ----------------------------------------------------------

    async def subscribe(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


def _put_nowait(queue: asyncio.Queue[Event], event: Event) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:  # slow consumer - drop the oldest event
        queue.get_nowait()
        queue.put_nowait(event)


bus = EventBus()
