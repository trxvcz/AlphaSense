"""Testy walidacji `Settings` (`core/config.py`).

Audyt bezpieczeństwa etap 2, znalezisko WYSOKIE: aplikacja musi odmówić
startu poza `env=dev`, jeśli `secret_key` jest pusty, publiczny (wartość
z `.env.example`) albo za krótki — cichy fallback na taką wartość na
produkcji podpisuje tokeny wartością, którą zna każdy, kto przeczytał repo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_VALID_PROD_SECRET = "a" * 32


def test_prod_with_default_secret_key_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(env="prod", secret_key="zmien-mnie")


def test_prod_with_empty_secret_key_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(env="prod", secret_key="")


def test_prod_with_short_secret_key_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(env="prod", secret_key="a" * 31)


def test_prod_with_valid_secret_key_passes() -> None:
    settings = Settings(env="prod", secret_key=_VALID_PROD_SECRET)
    assert settings.secret_key == _VALID_PROD_SECRET


def test_dev_with_default_secret_key_passes() -> None:
    settings = Settings(env="dev", secret_key="zmien-mnie")
    assert settings.secret_key == "zmien-mnie"
