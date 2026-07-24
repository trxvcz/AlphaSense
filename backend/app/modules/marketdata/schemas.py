"""Schematy Pydantic modułu `marketdata` (request/response) — plan krok 24,
etap 4: `GET /assets/search`, `GET /meta/freshness`.

Bez kwot pieniężnych w tym pliku — `assets`/`markets`/`ingestion_runs` nie
niosą wartości portfela, tylko metadane instrumentów i status ingestii.
Znaczniki czasu (`last_run_at`) zostają jako `datetime` (Pydantic serializuje
je do ISO 8601 domyślnie, spójnie z `UserOut.created_at` w
`modules/auth/schemas.py`) — kontrakt API mówi „Daty w formacie YYYY-MM-DD"
o `date`, nie o `datetime` ze strefą, więc to nie jest odstępstwo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AssetSearchResultOut(BaseModel):
    """Jeden wynik `GET /assets/search?q=`.

    Świadomie bez `sector`/`country` — te pola mogą być w trakcie
    uzupełniania w tle (`BackgroundTasks`, patrz `service.py`), zwracanie
    ich tutaj kusiłoby do pokazania stanu „w trakcie" jako ostatecznego.
    Kto potrzebuje pełnych metadanych, sięga po `GET /assets/{id}`
    (poza zakresem tego kroku).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    name: str
    asset_class: str
    market_code: str
    currency: str


class MarketFreshnessOut(BaseModel):
    """Świeżość danych EOD jednego rynku — jeden element `GET /meta/freshness`.

    `stale=True` i `last_run_at=None`/`status=None` jednocześnie oznacza:
    rynek istnieje w słowniku, ale nigdy nie miał przebiegu ingestii
    (`ingestion_runs` puste dla tego `market_code`) — to nie błąd 500, tylko
    stan „nieznana świeżość", patrz `service.get_markets_freshness`.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    last_run_at: datetime | None
    status: str | None
    stale: bool


class FreshnessOut(BaseModel):
    """Wyjście `GET /meta/freshness`."""

    markets: list[MarketFreshnessOut]
