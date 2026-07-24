"""Konfiguracja aplikacji — jedyne źródło prawdy.

Zero `os.getenv` rozsianego po kodzie (docs/konwencje.md). Wszystkie
zmienne odpowiadają nazwom z `.env.example` w korzeniu repo; wartości
domyślne poniżej to te same przykładowe (nie-sekretne) wartości co
w `.env.example`, żeby aplikacja startowała w dev bez dodatkowej
konfiguracji. Produkcja nadpisuje przez zmienne środowiskowe / `.env`.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ustawienia aplikacji czytane z `.env` / zmiennych środowiskowych."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- aplikacja ---
    env: str = "dev"
    secret_key: str = "zmien-mnie"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:3000"

    # --- baza i cache ---
    database_url: str = "postgresql+asyncpg://portfel:portfel@postgres:5432/portfel"
    redis_url: str = "redis://redis:6379/0"

    # --- dostawcy danych ---
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""
    coingecko_api_key: str = ""

    # --- limity dostawców (zapytania na minutę) ---
    rate_limit_stooq: int = 60
    rate_limit_yfinance: int = 30
    rate_limit_finnhub: int = 60
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: int = 600

    # --- OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- parametry analityczne (Decimal, nigdy float — CLAUDE.md #3.1) ---
    risk_free_rate: Decimal = Decimal("0.055")
    split_detection_threshold: Decimal = Decimal("0.4")
    min_observations_for_risk: int = 30

    # --- obserwowalność ---
    sentry_dsn: str = ""


@lru_cache
def get_settings() -> Settings:
    """Zwraca (raz zbudowany) obiekt ustawień."""
    return Settings()
