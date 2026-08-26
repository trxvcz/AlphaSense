"""Schematy Pydantic modułu `marketdata` (request/response) — plan krok 24,
etap 4: `GET /assets/search`, `GET /meta/freshness`. Rozszerzone w kroku 30
(etap 6) o `PricePointOut` — `GET /markets/{code}/index` i mini-seria
`series_30d` w `GET /portfolios/{portfolio_id}/markets`
(`app/modules/analytics/schemas.py`, ten sam kształt, reużyty stamtąd).

Bez kwot pieniężnych w większości tego pliku — `assets`/`markets`/
`ingestion_runs` nie niosą wartości portfela, tylko metadane instrumentów i
status ingestii. `close_adj` (`PricePointOut`) to wyjątek — to cena
instrumentu (indeksu), `Decimal`/string jak każda kwota (skill
`fastapi-modul`), nie procent ani metadana. Znaczniki czasu (`last_run_at`)
zostają jako `datetime` (Pydantic serializuje je do ISO 8601 domyślnie,
spójnie z `UserOut.created_at` w `modules/auth/schemas.py`) — kontrakt API
mówi „Daty w formacie YYYY-MM-DD" o `date`, nie o `datetime` ze strefą, więc
to nie jest odstępstwo.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


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


class PricePointOut(BaseModel):
    """Jeden punkt serii cenowej (`close_adj`, CLAUDE.md #4 — nigdy `close`
    surowe) — wyjście `GET /markets/{code}/index?range=` (lista rosnąco po
    dacie) i element `series_30d` w `GET /portfolios/{portfolio_id}/markets`
    (`app/modules/analytics/schemas.py` importuje ten schemat zamiast
    duplikować kształt — ten sam punkt danych w obu miejscach, krok 30)."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    close_adj: Decimal

    @field_serializer("close_adj")
    def _ser_close_adj(self, v: Decimal) -> str:
        return format(v, "f")


class CandleOut(BaseModel):
    """Jedna świeca `GET /assets/{id}/candles` (krok 45).

    Wszystkie cztery ceny **skorygowane** o splity i dywidendy współczynnikiem
    `close_adj / close` (`marketdata/candles.py`) — surowe OHLC z `prices`
    złamałoby CLAUDE.md #4 i rozjechałoby świece z linią zamknięcia na
    pozostałych wykresach aplikacji. Kwoty jako string (CLAUDE.md #3.1),
    `volume` jako liczba całkowita: to sztuki, nie pieniądze.
    """

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None

    @field_serializer("open", "high", "low", "close")
    def _ser_price(self, v: Decimal) -> str:
        return format(v, "f")


class CandleSeriesOut(BaseModel):
    """Wyjście `GET /assets/{id}/candles` (krok 45).

    `skipped` to liczba dni, których **nie da się** pokazać: brak kompletu
    OHLC albo `close <= 0`, czyli brak współczynnika korekty. Jest w
    odpowiedzi, bo wykres z dziurą wygląda dokładnie jak wykres kompletny,
    a dane niepełne mają być oznaczone (CLAUDE.md #3.15).
    """

    symbol: str
    name: str
    currency: str
    range: str
    skipped: int
    candles: list[CandleOut]
