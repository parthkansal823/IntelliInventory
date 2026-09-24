"""Runtime-editable settings stored in the database."""

from typing import Any

from app.db import session_scope
from app.models import Setting

DEFAULTS: dict[str, Any] = {
    "autopilot.enabled": None,  # None -> fall back to env config
    "agents.provider": None,
}


def get_setting(key: str, default: Any = None) -> Any:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None or row.value is None:
            return DEFAULTS.get(key) if default is None else default
        return row.value


def set_setting(key: str, value: Any) -> None:
    with session_scope() as s:
        row = s.get(Setting, key) or Setting(key=key)
        row.value = value
        s.add(row)
        s.commit()
