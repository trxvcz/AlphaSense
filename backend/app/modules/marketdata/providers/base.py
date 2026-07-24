"""Kontrakt dostawców danych rynkowych (`DataProvider`) i ich DTO.

Plan krok 20 (etap 4) — czysty fundament. Żaden konkretny dostawca
(NBP/Stooq/yfinance/Finnhub/Binance) nie powstaje w tym pliku, to kroki
21-22 (patrz `.claude/skills/data-provider/SKILL.md`).

**Decyzja: DTO jako zamrożone dataclassy, nie modele Pydantic.** `PriceBar`,
`FxQuote`, `AssetMetadata` nigdy nie przekraczają granicy HTTP — to nie
schematy `routes.py` (CLAUDE.md #8: warstwa `routes` waliduje, `service`
implementuje logikę, tu jesteśmy bliżej `service`/`repository`). Budowane
są *przez* kod konkretnego dostawcy z już poprawnie sparsowanych wartości
(np. `Decimal(text)` z komórki CSV Stooq albo z pola JSON, przeliczone
ręcznie w module dostawcy) — walidacja/koercja Pydantic (a zwłaszcza jego
domyślne, wyrozumiałe rzutowanie typów) tu tylko przeszkadzałaby i
maskowała błędy parsowania w miejscu, gdzie powinny być widoczne najwcześniej
(w kodzie dostawcy, nie dwa moduły dalej). `frozen=True` — te obiekty są
wynikiem jednego zapytania do API, nikt nie powinien ich mutować w locie;
`slots=True` dla mniejszego narzutu pamięciowego przy dużych zakresach dat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Capability(StrEnum):
    """Możliwości dostawcy. `FallbackChain` pomija w łańcuchu providerów,
    którzy nie obsługują żądanej możliwości (np. NBP nie ma `OHLCV`,
    Stooq nie ma `FX`) zamiast liczyć to jako porażkę.
    """

    OHLCV = "ohlcv"
    FX = "fx"
    METADATA = "metadata"
    SEARCH = "search"


@dataclass(frozen=True, slots=True)
class PriceBar:
    """Jedna świeca EOD zwrócona przez dostawcę — jeszcze bez `asset_id`;
    tłumaczenie symbolu dostawcy na aktywo w naszej bazie robi warstwa
    ingestii przez `asset_source_map` (CLAUDE.md #4, zasada 4), nie provider.

    Kwoty zawsze `Decimal` (CLAUDE.md #3.1), zero `float`. `close_adj` jest
    wymagane: dostawca bez ceny skorygowanej o dywidendy/splity ustawia
    `close_adj := close` i **sam odnotowuje ten fakt** (np. w wyniku ingestii)
    — `PriceBar` samo w sobie tego nie rozróżnia, to reguła 6 z CLAUDE.md.
    """

    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    close_adj: Decimal
    volume: int | None


@dataclass(frozen=True, slots=True)
class FxQuote:
    """Kurs walutowy zwrócony przez dostawcę (w praktyce wyłącznie NBP,
    tabela A — CLAUDE.md #3.5). Nazwa celowo różna od ORM
    `app.modules.marketdata.models.FxRate`, żeby nie mylić DTO transportowego
    (to, co zwraca provider) z wierszem tabeli `fx_rates` (to, co zapisuje
    warstwa ingestii po ewentualnym cofnięciu do `max(date) <= D`).
    """

    currency: str
    date: date
    rate_pln: Decimal


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    """Metadane aktywa zwrócone przez dostawcę. Tylko `symbol`/`name` są
    pewne — sektor/kraj/klasa aktywa zależą od providera i typu instrumentu
    (np. sektor dla ETF-u to zwykle przybliżenie albo `None`, patrz SKILL
    `data-provider`, tabela „Specyfika źródeł").
    """

    symbol: str
    name: str
    sector: str | None
    country: str | None
    asset_class: str | None


@runtime_checkable
class DataProvider(Protocol):
    """Kontrakt, który implementuje każdy konkretny dostawca (kroki 21-22)
    oraz — jako dekoratory nad konkretnym dostawcą — `Guarded`
    (`guarded.py`, ten sam pakiet).

    Provider nie zna bazy danych i nie zna `asset_id` — operuje wyłącznie na
    symbolu w SWOIM API (`asset_source_map.provider_symbol`); tłumaczenie
    robi warstwa ingestii (CLAUDE.md #4, zasada 4: „Symbol zewnętrzny nigdy
    nie jest sklejany w kodzie").
    """

    name: str
    supports: set[Capability]

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]: ...

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]: ...

    async def get_metadata(self, symbol: str) -> AssetMetadata | None: ...
