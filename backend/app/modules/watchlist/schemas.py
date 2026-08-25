"""Schematy Pydantic modułu `watchlist` (plan krok 43)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Nazwa listy nie może być pusta")
    return cleaned


class WatchlistCreateIn(BaseModel):
    """Wejście `POST /watchlists`."""

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return _clean_name(value)


class WatchlistUpdateIn(BaseModel):
    """Wejście `PATCH /watchlists/{watchlist_id}` — na razie tylko nazwa."""

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return _clean_name(value)


class WatchlistItemIn(BaseModel):
    """Wejście `PUT /watchlists/{watchlist_id}/items/{asset_id}`.

    `note` to notatka użytkownika, nie dana rynkowa — jedyny powód, dla
    którego watchlista jest czymś więcej niż zbiorem tickerów.
    """

    note: str | None = Field(default=None, max_length=500)


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    item_count: int


class WatchlistItemOut(BaseModel):
    """Pozycja listy z danymi słownikowymi aktywa.

    **Bez wyceny, bez ilości, bez zwrotu** — watchlista to lista
    obserwowanych, nie drugi portfel (CLAUDE.md #3.11). Dołożenie tu
    `value_pln` byłoby cichym rozszerzeniem zakresu v2.
    """

    asset_id: uuid.UUID
    symbol: str
    name: str
    market_code: str
    currency: str
    note: str | None
    added_at: datetime
