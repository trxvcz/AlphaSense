"""Modele ORM modułu `marketdata`: `markets`, `assets`, `prices`,
`asset_source_map`, `fx_rates`, `ingestion_runs`.

Plan krok 17-18 (etap 3). Słownik rynków (ADR-102) — `markets.code` jest
naturalnym kluczem tekstowym (nie `UUID`), godziny jobów EOD (`eod_time`)
czyta worker z tej tabeli, nie z hardkodu. Cykl FK `markets ⇄ assets`
(`markets.index_asset_id → assets.id`, `assets.market_code → markets.code`)
jest tu widoczny w Pythonie bez problemu (SQLAlchemy rozwiązuje FK przez
odroczone łańcuchy stringów `ForeignKey("...")`) — problem cykliczny
dotyczy tylko **kolejności migracji Alembic** (patrz skill
`alembic-migracja`, sekcja „Kolejność tworzenia tabel”), nie tego modułu.

Żadny FK w tym pliku nie kaskaduje `ON DELETE CASCADE` z `users` — dane
rynkowe (`assets`, `prices`, `markets`, ...) nie są własnością użytkownika,
CLAUDE.md #3.5 dotyczy tylko ścieżki `users → portfolios → holdings/
portfolio_valuations` (patrz `app/modules/portfolio/models.py`).

Seed słownika rynków (`docs/slownik-rynkow.md`), `DataProvider` i
ingestion EOD (`service.py`, `worker/jobs/`) — kolejne kroki planu (etap 4),
poza zakresem tego pliku.
"""

from __future__ import annotations

import uuid
from datetime import date as date_
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Market(Base):
    """Słownik rynków (ADR-102) — jedno źródło prawdy dla stref czasowych
    i godzin EOD, które czyta worker (CLAUDE.md #3.6).

    `index_asset_id` (FK → `assets.id`) wskazuje na aktywo reprezentujące
    indeks referencyjny rynku (np. WIG dla GPW) — dodane w osobnej migracji
    addytywnej *po* utworzeniu `assets`, żeby rozwiązać cykl FK.
    """

    __tablename__ = "markets"

    code: Mapped[str] = mapped_column(String(), primary_key=True)
    name: Mapped[str] = mapped_column(String())
    index_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
        default=None,
    )
    timezone: Mapped[str] = mapped_column(String())
    eod_time: Mapped[time] = mapped_column(Time())


class Asset(Base):
    """Aktywo (akcja, ETF, krypto, ...) notowane na jednym rynku.

    Sektor/kraj/region pochodzą domyślnie od dostawcy (`metadata_source`
    zapisuje który), override użytkownika ma pierwszeństwo (poza zakresem
    tego pliku — logika w `service.py`, etap 4). `is_active=False` wygasza
    aktywo bez usuwania (zachowuje historię `prices`, `holdings`).
    """

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_market_code", "market_code"),
        Index("ix_assets_symbol", "symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    symbol: Mapped[str] = mapped_column(String())
    name: Mapped[str] = mapped_column(String())
    asset_class: Mapped[str] = mapped_column(String())
    market_code: Mapped[str] = mapped_column(String(), ForeignKey("markets.code"))
    currency: Mapped[str] = mapped_column(String(3))
    isin: Mapped[str | None] = mapped_column(String(), default=None)
    sector: Mapped[str | None] = mapped_column(String(), default=None)
    country: Mapped[str | None] = mapped_column(String(), default=None)
    region: Mapped[str | None] = mapped_column(String(), default=None)
    metadata_source: Mapped[str | None] = mapped_column(String(), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean(), server_default=text("true"))


class Price(Base):
    """Dzienna świeca EOD dla aktywa. Wycena i wykresy zawsze na `close_adj`
    (CLAUDE.md #4), nigdy na surowym `close`.
    """

    __tablename__ = "prices"
    __table_args__ = (CheckConstraint("close_adj > 0", name="close_adj_positive"),)

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
        primary_key=True,
    )
    date: Mapped[date_] = mapped_column(Date(), primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    close_adj: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    volume: Mapped[int | None] = mapped_column(BigInteger(), default=None)
    # Nazwa dostawcy, od którego pochodzi TEN wiersz (`Guarded.name`:
    # `yfinance`, `stooq`, `finnhub`, `binance`, `nbp`). Nie jest ozdobą
    # diagnostyczną — konwencje `close_adj` między dostawcami są
    # niekompatybilne: yfinance oddaje realną cenę skorygowaną o dywidendy
    # i splity, a Stooq/Finnhub/Binance wpisują `close_adj := close`
    # (patrz docstringi providerów). Łańcuch fallbacku rozstrzyga się per
    # zapytanie, więc jedna seria potrafi wymieszać obie konwencje i
    # wyprodukować na styku skok rzędu kilkunastu procent, którego nie
    # widać w surowym `close` (czyli i heurystyka splitu z kroku 28 go nie
    # złapie). Bez tej kolumny nie da się takiej serii ani wykryć, ani
    # naprawić — a kroki 40-42 policzyłyby ten skok jako realny zwrot.
    #
    # `NULL` = wiersz sprzed tej kolumny, źródło nieznane. Świadomie nie
    # zgadujemy go wstecz: „nie wiem" jest tu informacją, a wpisanie
    # prawdopodobnego dostawcy zamieniłoby brak wiedzy w fałszywą pewność.
    source: Mapped[str | None] = mapped_column(String(), default=None)


# Indeks `(asset_id, date DESC)` — wykresy i wycena czytają najnowsze ceny
# jako pierwsze; `.desc()` wymaga atrybutu klasy, stąd poza `__table_args__`
# (jak `PortfolioValuation`, patrz `app/modules/portfolio/models.py`).
Index("ix_prices_asset_id_date_desc", Price.asset_id, Price.date.desc())


class AssetSourceMap(Base):
    """Mapowanie aktywa na symbol u konkretnego dostawcy danych, z
    priorytetem — warunek działania fallbacku między dostawcami (etap 4).
    """

    __tablename__ = "asset_source_map"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(), primary_key=True)
    provider_symbol: Mapped[str] = mapped_column(String())
    priority: Mapped[int] = mapped_column(Integer())


class FxRate(Base):
    """Kurs walutowy NBP (tabela A) względem PLN.

    Lookup `max(date) <= D` (cofanie do ostatniego dnia roboczego,
    CLAUDE.md #3.5) — logika w `service.py`, poza zakresem tego pliku.
    """

    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[date_] = mapped_column(Date(), primary_key=True)
    rate_pln: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class IngestionRun(Base):
    """Log przebiegu ingestii EOD dla jednego rynku — podstawa
    `/meta/freshness` i alertów (etap 4/6).
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    market_code: Mapped[str] = mapped_column(String(), ForeignKey("markets.code"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    provider: Mapped[str] = mapped_column(String())
    assets_total: Mapped[int] = mapped_column(Integer())
    assets_ok: Mapped[int] = mapped_column(Integer())
    status: Mapped[str] = mapped_column(String())
    error: Mapped[str | None] = mapped_column(String(), default=None)


# Indeks `(market_code, started_at DESC)` — `/meta/freshness` czyta ostatni
# przebieg per rynek jako pierwszy; `.desc()` poza `__table_args__` (jak
# wyżej).
Index(
    "ix_ingestion_runs_market_code_started_at_desc",
    IngestionRun.market_code,
    IngestionRun.started_at.desc(),
)


class NbpReferenceRate(Base):
    """Stopa referencyjna NBP obowiązująca od `effective_from` (krok 41a).

    Wiersz = **zmiana stopy**, nie dzień. NBP publikuje decyzje RPP, a nie
    szereg dzienny, więc kopiowanie tej samej wartości na każdy dzień
    kalendarzowy byłoby zapisywaniem danych, których źródło nie ma.
    Obowiązywanie „do następnej zmiany" wynika z lookupu
    `max(effective_from) <= D` przy odczycie (`repository.
    get_reference_rate`) — ten sam wzorzec co `fx_rates` (CLAUDE.md #3.5).

    `rate` to **ułamek roczny** (`0.03750000` = 3,75% p.a.), nie procent —
    patrz `providers/nbp_rates.ReferenceRate`.

    Dana nie należy do użytkownika (jak `fx_rates`, `prices`, `news`), więc
    żaden FK nie prowadzi do `users`.
    """

    __tablename__ = "nbp_reference_rates"

    effective_from: Mapped[date_] = mapped_column(Date(), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
