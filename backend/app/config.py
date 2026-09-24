"""Application settings, loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "IntelliInventory"
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'intelliinventory.db'}"
    seed_demo_data: bool = True
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    secret_key: str = "change-me-in-production-intelliinventory-secret"
    access_token_minutes: int = 60 * 12
    demo_password: str = "demo1234"
    # Shared secret for machine clients (Hermes Agent plugin/hooks, MCP over HTTP).
    integration_token: str = "hermes-dev-token"
    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"

    # --- AI providers -------------------------------------------------------
    # "auto" = zero-cost first: Hermes (configured endpoint, or a local Ollama
    # running a Hermes model - auto-detected), then Claude only if you supplied
    # a key, otherwise the built-in offline planner (no LLM, no cost).
    ai_provider: Literal["auto", "hermes", "claude", "offline"] = "auto"

    # Nous Research Hermes models through any OpenAI-compatible endpoint.
    # Free & local by default: Ollama (`ollama pull hermes3`). Also works with
    # Nous Portal, OpenRouter, vLLM, llama.cpp, LM Studio ...
    hermes_base_url: str | None = None  # default: http://localhost:11434/v1 (Ollama)
    hermes_api_key: str | None = None
    hermes_model: str = "hermes3"
    ollama_url: str = "http://localhost:11434"
    ollama_autodetect: bool = True
    # "native" = OpenAI `tools` param; "prompt" = Hermes <tool_call> XML format
    hermes_tool_mode: Literal["native", "prompt"] = "native"

    # Anthropic Claude. Model/effort/fallbacks use an II_ prefix because Claude Code itself
    # exports CLAUDE_* variables (e.g. CLAUDE_EFFORT) that must not leak into the app.
    anthropic_api_key: str | None = None
    claude_model: str = Field("claude-opus-5", validation_alias="II_CLAUDE_MODEL")
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field("medium", validation_alias="II_CLAUDE_EFFORT")
    # Server-side refusal fallbacks ("default" routes by refusal category, "off" disables)
    claude_fallbacks: Literal["default", "off"] = Field("default", validation_alias="II_CLAUDE_FALLBACKS")

    agent_max_steps: int = 8

    # --- Automation ---------------------------------------------------------
    autopilot_enabled: bool = True
    autopilot_cooldown_hours: int = 12
    webhook_timeout_seconds: float = 5.0
    plugins_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
