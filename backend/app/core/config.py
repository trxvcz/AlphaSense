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

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Wartość przykładowa z `.env.example` — publiczna, nigdy nie wolno jej użyć
# poza `env=dev` (audyt bezpieczeństwa, etap 2).
_INSECURE_DEFAULT_SECRET_KEY = "zmien-mnie"
_MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Ustawienia aplikacji czytane z `.env` / zmiennych środowiskowych."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- aplikacja ---
    env: str = "dev"
    # Wersja wdrożonego kodu — zwracana przez `GET /api/health` i wysyłana do
    # Sentry jako `release`, żeby dało się powiedzieć „ten błąd przyszedł z
    # wdrożenia X". Na produkcji ustawiana ze zmiennej środowiskowej (np. na
    # skrót commita), patrz `docs/wdrozenie.md`.
    app_version: str = "0.1.0"
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

    # --- limity dostawców (zapytania na minutę) ---
    rate_limit_stooq: int = 60
    rate_limit_yfinance: int = 30
    rate_limit_finnhub: int = 60
    # Binance: publiczne REST, bez klucza, limit oparty o wagę (1200/min na
    # IP przy wadze 2 dla `/klines` — 60/min to konserwatywny, spójny domyślny
    # limit z resztą dostawców, nie twardy limit Binance).
    rate_limit_binance: int = 60
    # NBP nie publikuje twardego limitu zapytań (API publiczne, bez klucza)
    # — 60/min to ten sam konserwatywny domyślny limit co reszta dostawców
    # bez udokumentowanego limitu (Binance wyżej), nie wartość zmierzona.
    rate_limit_nbp: int = 60
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: int = 600

    # --- rate limiting API (slowapi, krok 16) ---
    # Liczniki w Redisie (`storage_uri=redis_url`), nie w pamięci procesu —
    # przetrwają restart/wiele replik API (patrz `core/rate_limit.py`).
    rate_limit_default_per_minute: int = 100
    rate_limit_auth_per_minute: int = 5

    # --- OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""
    # Musi dosłownie zgadzać się z „Authorized redirect URI" skonfigurowanym
    # w Google Cloud Console — Google odrzuci wymianę kodu przy niezgodności.
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # --- parametry analityczne (Decimal, nigdy float — CLAUDE.md #3.1) ---
    risk_free_rate: Decimal = Decimal("0.055")
    split_detection_threshold: Decimal = Decimal("0.4")
    min_observations_for_risk: int = 30

    # --- obserwowalność ---
    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _validate_secret_key_outside_dev(self) -> Settings:
        """Odmawia startu poza `env=dev`, jeśli `secret_key` nie jest bezpieczny.

        Bezpieczeństwo (audyt etap 2, znalezisko WYSOKIE): pusty, publiczny
        (ten sam co w `.env.example`) albo za krótki `secret_key` podpisuje
        access tokeny i cookie stanu OAuth (`core/security.py`) — cichy
        fallback na taką wartość na produkcji to możliwość podrobienia
        tokenu przez kogokolwiek, kto przeczytał ten plik.
        """
        if self.env == "dev":
            return self
        if (
            not self.secret_key
            or self.secret_key == _INSECURE_DEFAULT_SECRET_KEY
            or len(self.secret_key) < _MIN_SECRET_KEY_LENGTH
        ):
            raise ValueError(
                "SECRET_KEY musi być ustawiony na losową wartość o długości "
                f"co najmniej {_MIN_SECRET_KEY_LENGTH} znaków, gdy ENV != 'dev' "
                "(nie wolno używać wartości domyślnej z .env.example)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Zwraca (raz zbudowany) obiekt ustawień."""
    return Settings()
