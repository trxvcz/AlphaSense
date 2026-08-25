"""Schematy Pydantic modułu `tags` (plan krok 43).

Nazwa jest przycinana z białych znaków i **nie może być pusta** — inaczej
w filtrze pojawiłaby się etykieta bez treści, nie do wybrania i nie do
usunięcia z widoku. To samo ograniczenie stoi w bazie
(`ck_tags_name_not_blank`) jako ostatnia linia obrony.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# `#rrggbb` — jedyny format, jaki przyjmujemy. Walidacja tu, nie w bazie:
# paleta należy do prezentacji, a baza trzyma tylko `String(7)`.
_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Nazwa tagu nie może być pusta")
    return cleaned


class TagCreateIn(BaseModel):
    """Wejście `POST /tags`."""

    name: str = Field(min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=_COLOR_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return _clean_name(value)


class TagUpdateIn(BaseModel):
    """Wejście `PATCH /tags/{tag_id}` — oba pola opcjonalne.

    Jawny `"color": null` znaczy **skasuj kolor**, a pominięcie pola —
    „nie zmieniaj". Te dwa przypadki rozróżnia `model_fields_set` w trasie;
    zlanie ich do jednego kasowałoby kolor przy każdej zmianie nazwy.
    """

    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=_COLOR_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class TagOut(BaseModel):
    """Tag użytkownika. `asset_count` liczy TYLKO aktywa otagowane przez
    tego użytkownika — `assets` jest słownikiem globalnym, więc licznik bez
    zawężenia byłby liczbą cudzych decyzji."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime
    asset_count: int


class TagAssetOut(BaseModel):
    """Aktywo otagowane danym tagiem — tyle danych słownikowych, ile
    potrzeba, żeby pokazać wiersz bez drugiego zapytania."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    name: str
    market_code: str
    currency: str
