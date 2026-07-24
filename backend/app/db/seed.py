"""Seed danych startowych: słownik rynków (ADR-102), demo aktywa i demo
użytkownik z portfelem.

Wołane przez `python -m app.cli seed` (`make seed`, plan krok 19, etap 3).
Cross-modułowe z rozmysłem (dotyka `auth`, `marketdata`, `portfolio`) — nie
jest logiką domenową jednego modułu, tylko jednorazowym/wielorazowym
przygotowaniem środowiska dev, stąd `app/db/`, obok `session.py`/`base.py`,
a nie w którymś z `app/modules/*`.

Idempotencja: każde `_get_or_create_*` sprawdza istnienie przed insertem,
zamiast `INSERT ... ON CONFLICT` wszędzie — `assets` nie ma naturalnego
klucza unikalnego (`id` to losowy UUID generowany po stronie serwera przy
każdym insercie, `ON CONFLICT (id)` nie chroniłby przed dwoma wierszami tego
samego symbolu na tym samym rynku), więc jednolity wzorzec „sprawdź po
kluczu naturalnym, wstaw jeśli brak" jest prostszy do utrzymania niż
mieszanka `ON CONFLICT` (tam gdzie klucz unikalny istnieje: `markets.code`,
`users.email`) i ręcznego sprawdzania (tam gdzie nie istnieje: `assets`,
`portfolios`). Drugie i kolejne uruchomienie `make seed` nie duplikuje
wierszy i nie nadpisuje istniejących danych — w tym nie generuje nowego
hasła demo użytkownika, jeśli już istnieje (patrz `SeedResult.demo_password`).

Cykl FK `markets ⇄ assets` (skill `alembic-migracja`, sekcja „Kolejność
tworzenia tabel") wymusza kolejność w `seed_all`:
1. `markets` (bez `index_asset_id` — kolumna jest `NULL`-na do kroku 3)
2. `assets` — najpierw indeksy referencyjne, potem demo aktywa tradowalne
3. `UPDATE markets SET index_asset_id = ...` (teraz `assets` już istnieją)
4. demo `User` → `Portfolio` → `Holding`
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.marketdata.models import Asset, Market
from app.modules.portfolio.models import Holding, Portfolio

# .example: RFC 2606, gwarantowana nierozwiązywalna domena demo
DEMO_USER_EMAIL = "demo@alphasense.example"
DEMO_PORTFOLIO_NAME = "Portfel demo"
# `portfolios.type` nie ma jeszcze enuma/CHECK (CRUD portfeli i jego walidacja
# to etap 5, poza zakresem seedu) — wartość wolna tekstowa, ale sensowna.
DEMO_PORTFOLIO_TYPE = "standard"

# Metadane sposobu powstania wiersza — odróżnia dane seedowe od tych, które
# w etapie 4 wpisze `DataProvider` (kolumna już istnieje w modelu `Asset`).
_SEED_METADATA_SOURCE = "seed"


@dataclass(frozen=True, slots=True)
class MarketSeed:
    """Jeden wiersz `docs/slownik-rynkow.md` bez kolumny `index_asset_id`."""

    code: str
    name: str
    timezone: str
    eod_time: time


@dataclass(frozen=True, slots=True)
class AssetSeed:
    """Jedno aktywo (indeks referencyjny albo demo aktywo tradowalne)."""

    symbol: str
    name: str
    asset_class: str
    market_code: str
    currency: str
    sector: str | None = None
    country: str | None = None
    region: str | None = None


@dataclass(frozen=True, slots=True)
class HoldingSeed:
    """Jedna demo pozycja w portfelu demo użytkownika."""

    symbol: str
    market_code: str
    quantity: Decimal
    avg_cost: Decimal
    cost_currency: str


# 12 rynków z `docs/slownik-rynkow.md` (ADR-102).
MARKETS: tuple[MarketSeed, ...] = (
    MarketSeed("GPW", "Giełda Papierów Wartościowych", "Europe/Warsaw", time(18, 30)),
    MarketSeed("US", "NYSE / NASDAQ", "America/New_York", time(23, 15)),
    MarketSeed("US_TECH", "NASDAQ (tech)", "America/New_York", time(23, 15)),
    MarketSeed("XETRA", "Deutsche Börse", "Europe/Berlin", time(18, 0)),
    MarketSeed("LSE", "London Stock Exchange", "Europe/London", time(18, 15)),
    MarketSeed("EURONEXT", "Euronext (Paryż/Amsterdam)", "Europe/Paris", time(18, 0)),
    MarketSeed("SIX", "SIX Swiss Exchange", "Europe/Zurich", time(18, 0)),
    MarketSeed("TSE", "Tokyo Stock Exchange", "Asia/Tokyo", time(9, 0)),
    MarketSeed("HKEX", "Hong Kong", "Asia/Hong_Kong", time(10, 30)),
    MarketSeed("CRYPTO", "Rynek krypto (24/7)", "UTC", time(0, 30)),
    MarketSeed("COMMODITY", "Surowce", "Europe/Warsaw", time(12, 35)),
    MarketSeed("FX", "Waluty (NBP tabela A)", "Europe/Warsaw", time(12, 35)),
)

# Indeksy referencyjne — jeden na rynek, poza `FX` (rynek bez indeksu,
# `docs/slownik-rynkow.md`: „pokazuje w rankingu samą wagę"). Symbole
# dosłownie te z zadania/dokumentu (nie symbole dostawcy — te żyją w
# `asset_source_map`, etap 4, poza zakresem tego kroku).
INDEX_ASSETS: tuple[AssetSeed, ...] = (
    AssetSeed("WIG20", "WIG20", "index", "GPW", "PLN", country="Polska", region="Europa"),
    AssetSeed("^GSPC", "S&P 500", "index", "US", "USD", country="USA", region="Ameryka Północna"),
    AssetSeed(
        "^NDX", "NASDAQ 100", "index", "US_TECH", "USD", country="USA", region="Ameryka Północna"
    ),
    AssetSeed("^GDAXI", "DAX", "index", "XETRA", "EUR", country="Niemcy", region="Europa"),
    AssetSeed(
        "^FTSE", "FTSE 100", "index", "LSE", "GBP", country="Wielka Brytania", region="Europa"
    ),
    AssetSeed("^FCHI", "CAC 40", "index", "EURONEXT", "EUR", country="Francja", region="Europa"),
    AssetSeed("^SSMI", "SMI", "index", "SIX", "CHF", country="Szwajcaria", region="Europa"),
    AssetSeed("^N225", "Nikkei 225", "index", "TSE", "JPY", country="Japonia", region="Azja"),
    AssetSeed("^HSI", "Hang Seng", "index", "HKEX", "HKD", country="Hongkong", region="Azja"),
    AssetSeed("bitcoin", "Bitcoin", "crypto", "CRYPTO", "USD", region="Globalny"),
    AssetSeed("XAU", "Złoto", "commodity", "COMMODITY", "USD", region="Globalny"),
)

# Kilka demo aktywów tradowalnych (nie indeksów) do zasilenia demo portfela.
# Sektor/kraj/region są danymi seedowymi — sensownymi, nie „na sekundę"
# rzeczywistymi (override i realne dane przychodzą z `DataProvider`, etap 4).
DEMO_ASSETS: tuple[AssetSeed, ...] = (
    AssetSeed(
        "CDR",
        "CD Projekt",
        "equity",
        "GPW",
        "PLN",
        sector="gaming",
        country="Polska",
        region="Europa",
    ),
    AssetSeed(
        "PKN",
        "PKN Orlen",
        "equity",
        "GPW",
        "PLN",
        sector="energy",
        country="Polska",
        region="Europa",
    ),
    AssetSeed(
        "AAPL",
        "Apple Inc.",
        "equity",
        "US",
        "USD",
        sector="technology",
        country="USA",
        region="Ameryka Północna",
    ),
    AssetSeed(
        "MSFT",
        "Microsoft Corp.",
        "equity",
        "US",
        "USD",
        sector="technology",
        country="USA",
        region="Ameryka Północna",
    ),
)

# Bitcoin w demo portfelu wskazuje na **ten sam** rekord `Asset`, co indeks
# referencyjny rynku `CRYPTO` (`INDEX_ASSETS`, symbol `bitcoin`) — świadoma
# decyzja, nie osobny rekord `BTC`. To dosłownie ten sam instrument z jednym
# szeregiem `prices`; osobny rekord "BTC" duplikowałby dane cenowe i
# wymagałby decyzji, który z dwóch wierszy aktualizuje ingestion EOD rynku
# `CRYPTO` (etap 4). `holdings.asset_id` i tak wskazuje wyłącznie na jeden z
# nich, więc reużycie nie koliduje z niczym w modelu.
DEMO_HOLDINGS: tuple[HoldingSeed, ...] = (
    HoldingSeed("CDR", "GPW", Decimal("10"), Decimal("120.50"), "PLN"),
    HoldingSeed("PKN", "GPW", Decimal("25"), Decimal("65.20"), "PLN"),
    HoldingSeed("AAPL", "US", Decimal("5"), Decimal("180.00"), "USD"),
    HoldingSeed("MSFT", "US", Decimal("3"), Decimal("410.00"), "USD"),
    HoldingSeed("bitcoin", "CRYPTO", Decimal("0.1"), Decimal("60000.00"), "USD"),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Wynik `seed_all` — CLI (`app/cli.py`) używa go do komunikatu na konsoli."""

    demo_user_email: str
    # `None` = demo użytkownik już istniał, hasło NIE zostało zmienione
    # (idempotencja — drugi przebieg `make seed` nie unieważnia hasła z
    # pierwszego).
    demo_password: str | None


async def _get_or_create_market(session: AsyncSession, seed: MarketSeed) -> None:
    existing = await session.get(Market, seed.code)
    if existing is not None:
        return
    session.add(
        Market(code=seed.code, name=seed.name, timezone=seed.timezone, eod_time=seed.eod_time)
    )


async def _get_or_create_asset(session: AsyncSession, seed: AssetSeed) -> Asset:
    """Klucz naturalny idempotencji: `(symbol, market_code)` — `assets` nie ma
    na to `UNIQUE` w schemacie (poza zakresem tego kroku), stąd sprawdzenie
    w Pythonie, nie `ON CONFLICT`.
    """
    existing = await session.scalar(
        select(Asset).where(Asset.symbol == seed.symbol, Asset.market_code == seed.market_code)
    )
    if existing is not None:
        return existing

    asset = Asset(
        symbol=seed.symbol,
        name=seed.name,
        asset_class=seed.asset_class,
        market_code=seed.market_code,
        currency=seed.currency,
        sector=seed.sector,
        country=seed.country,
        region=seed.region,
        metadata_source=_SEED_METADATA_SOURCE,
    )
    session.add(asset)
    await session.flush()  # potrzebujemy asset.id (server_default) od razu
    return asset


async def _link_market_index(
    session: AsyncSession, *, market_code: str, index_asset_id: uuid.UUID
) -> None:
    market = await session.get(Market, market_code)
    if market is None:
        raise RuntimeError(f"rynek {market_code!r} musi istnieć przed powiązaniem indeksu")
    if market.index_asset_id is None:
        market.index_asset_id = index_asset_id


async def _get_or_create_demo_user(session: AsyncSession) -> tuple[User, str | None]:
    existing = await session.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
    if existing is not None:
        return existing, None

    raw_password = secrets.token_urlsafe(12)
    user = User(email=DEMO_USER_EMAIL, password_hash=hash_password(raw_password))
    session.add(user)
    await session.flush()  # potrzebujemy user.id od razu (Portfolio.user_id)
    return user, raw_password


async def _get_or_create_demo_portfolio(session: AsyncSession, *, user_id: uuid.UUID) -> Portfolio:
    existing = await session.scalar(
        select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.name == DEMO_PORTFOLIO_NAME)
    )
    if existing is not None:
        return existing

    portfolio = Portfolio(user_id=user_id, name=DEMO_PORTFOLIO_NAME, type=DEMO_PORTFOLIO_TYPE)
    session.add(portfolio)
    await session.flush()  # potrzebujemy portfolio.id od razu (Holding.portfolio_id)
    return portfolio


async def _get_or_create_holding(
    session: AsyncSession, *, portfolio_id: uuid.UUID, asset_id: uuid.UUID, seed: HoldingSeed
) -> None:
    existing = await session.scalar(
        select(Holding).where(Holding.portfolio_id == portfolio_id, Holding.asset_id == asset_id)
    )
    if existing is not None:
        return
    session.add(
        Holding(
            portfolio_id=portfolio_id,
            asset_id=asset_id,
            quantity=seed.quantity,
            avg_cost=seed.avg_cost,
            cost_currency=seed.cost_currency,
        )
    )


async def seed_all(session: AsyncSession) -> SeedResult:
    """Zasiej rynki, indeksy referencyjne, demo aktywa i demo użytkownika z
    portfelem. Commituje na końcu (jedna transakcja, wszystko albo nic).
    """
    # 1. markets (bez index_asset_id)
    for market_seed in MARKETS:
        await _get_or_create_market(session, market_seed)
    await session.flush()  # markets.code musi być widoczne przed insertem assets (FK)

    # 2. assets — najpierw indeksy referencyjne, potem demo aktywa tradowalne
    index_assets_by_market: dict[str, Asset] = {}
    for asset_seed in INDEX_ASSETS:
        index_assets_by_market[asset_seed.market_code] = await _get_or_create_asset(
            session, asset_seed
        )

    demo_assets_by_symbol: dict[str, Asset] = {}
    for asset_seed in DEMO_ASSETS:
        demo_assets_by_symbol[asset_seed.symbol] = await _get_or_create_asset(session, asset_seed)
    # patrz komentarz przy `DEMO_HOLDINGS` — reużycie rekordu indeksu CRYPTO
    demo_assets_by_symbol["bitcoin"] = index_assets_by_market["CRYPTO"]

    # 3. UPDATE markets SET index_asset_id = ... (assets już istnieją)
    for market_code, asset in index_assets_by_market.items():
        await _link_market_index(session, market_code=market_code, index_asset_id=asset.id)

    # 4. demo User → Portfolio → Holding
    user, raw_password = await _get_or_create_demo_user(session)
    portfolio = await _get_or_create_demo_portfolio(session, user_id=user.id)
    for holding_seed in DEMO_HOLDINGS:
        asset = demo_assets_by_symbol[holding_seed.symbol]
        await _get_or_create_holding(
            session, portfolio_id=portfolio.id, asset_id=asset.id, seed=holding_seed
        )

    await session.commit()
    return SeedResult(demo_user_email=user.email, demo_password=raw_password)
