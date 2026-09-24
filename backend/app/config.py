"""Application settings, loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
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

    # Deployment mode. Demo: sample data + one-click demo logins on the login page.
    # Actual (DEMO_MODE=false): empty catalogue, a single admin from ADMIN_EMAIL / ADMIN_PASSWORD.
    demo_mode: bool = True
    gst_enabled: bool = True  # default for the Settings → Business "GST registered" switch
    seed_demo_data: bool | None = None  # defaults to demo_mode
    admin_email: str = "admin@example.com"
    admin_name: str = "Administrator"
    admin_password: str | None = None  # generated and logged once if unset
    # Public base URL (Render sets RENDER_EXTERNAL_URL automatically)
    public_url: str | None = Field(None, validation_alias=AliasChoices("PUBLIC_URL", "RENDER_EXTERNAL_URL"))
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    secret_key: str = "change-me-in-production-intelliinventory-secret"
    access_token_minutes: int = 60 * 12
    demo_password: str = "demo1234"
    # Shared secret for machine clients (Hermes Agent plugin/hooks, MCP over HTTP).
    integration_token: str = "hermes-dev-token"
    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"

    # --- AI providers -------------------------------------------------------
    # 100% free: "auto" uses a Hermes model if one is reachable (e.g. local Ollama, auto-detected),
    # otherwise the built-in offline planner. No paid API is ever required.
    ai_provider: Literal["auto", "hermes", "offline"] = "auto"

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

    agent_max_steps: int = 8

    # --- Automation ---------------------------------------------------------
    autopilot_enabled: bool = True
    autopilot_cooldown_hours: int = 12
    webhook_timeout_seconds: float = 5.0
    plugins_dir: Path | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Hosted Postgres (Neon, Supabase, Render) hands out postgres:// URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @property
    def should_seed_demo(self) -> bool:
        return self.demo_mode if self.seed_demo_data is None else self.seed_demo_data


@lru_cache
def get_settings() -> Settings:
    return Settings()
