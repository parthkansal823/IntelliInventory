"""Provider registry and zero-cost-first resolution."""

from __future__ import annotations

from app.config import get_settings
from app.services.settings import get_setting

from .base import Provider, ProviderError
from .hermes import HermesProvider
from .offline import OfflineProvider

PROVIDERS: dict[str, type[Provider]] = {
    "hermes": HermesProvider,
    "offline": OfflineProvider,
}
_instances: dict[str, Provider] = {}

SETUP_HINTS = {
    "hermes": "Free & local: install Ollama, run `ollama pull hermes3`, keep it running — auto-detected. "
    "Or set HERMES_BASE_URL / HERMES_API_KEY for Nous Portal, OpenRouter, vLLM or LM Studio.",
    "offline": "Built in. Deterministic planner, no model, no cost.",
}


def resolve_provider_name(requested: str | None = None) -> str:
    name = requested or get_setting("agents.provider") or get_settings().ai_provider
    if name == "auto":
        # Always free: a local/configured Hermes model if one is available, otherwise the offline planner.
        return "hermes" if PROVIDERS["hermes"].configured() else "offline"
    if name not in PROVIDERS or not PROVIDERS[name].configured():
        return "offline"
    return name


def get_provider(requested: str | None = None) -> Provider:
    name = resolve_provider_name(requested)
    if name not in _instances or name == "hermes":  # hermes re-resolves the local model each time
        _instances[name] = PROVIDERS[name]()
    return _instances[name]


def describe_providers() -> list[dict]:
    out = []
    for name, cls in PROVIDERS.items():
        info = {"name": name, "label": cls.label, "configured": cls.configured()}
        if info["configured"]:
            try:
                info.update(get_provider(name).describe() if resolve_provider_name(name) == name else {})
            except Exception as exc:  # noqa: BLE001
                info["error"] = str(exc)
        info.setdefault("free", name in ("offline", "hermes"))
        info["setup"] = SETUP_HINTS[name]
        out.append(info)
    return out


__all__ = ["PROVIDERS", "Provider", "ProviderError", "describe_providers", "get_provider", "resolve_provider_name"]
