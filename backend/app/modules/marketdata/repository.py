"""Zapis/odczyt danych rynkowych (`fx_rates`, `prices`) — warstwa dzieląca
się między wszystkich dostawców (plan krok 21, etap 4).

Rozszerzone w kroku 30 (etap 6, ranking rynków ADR-102) o odczyty potrzebne
`analytics.service.market_ranking` (`get_asset`, `list_markets_by_codes`,
`get_latest_prices`) i `GET /markets/{code}/index`
(`get_market`, `list_prices_in_range`).

Świadomie osobne, wąskie funkcje zamiast jednej klasy „repozytorium" (skill
`data-provider`, sekcja „Reguły twarde" #3; zadanie kroku 21 wprost prosi o
kształt łatwy do bezkonfliktowego rozszerzania, bo krok 22 — Stooq/yfinance/
Finnhub, inny równoległy agent — dopisze tu kolejne funkcje, np.
`upsert_asset_metadata`). Funkcje w tym module **nie znają** konkretnego
providera (NBP/Stooq/...) — przyjmują już zbudowane DTO (`FxQuote`,
`PriceBar`) i zapisują je idempotentnie.

Zapis zawsze `INSERT ... ON CONFLICT (...) DO UPDATE` (nigdy zwykły
`INSERT`, nigdy „usuń i wstaw ponownie") — ponowne uruchomienie joba EOD za
ten sam dzień nadpisuje, nie duplikuje (CLAUDE.md #3.9).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import (
    Asset,
    AssetSourceMap,
    FxRate,
    IngestionRun,
    Market,
    NbpReferenceRate,
    Price,
)
from app.modules.marketdata.providers.base import FxQuote, PriceBar
from app.modules.marketdata.providers.nbp_rates import ReferenceRate

logger = structlog.get_logger(__name__)

# `?range=` w `GET /markets/{code}/index` — ten sam zestaw wartości i ta sama
# logika liczenia dolnej granicy daty co `portfolio/repository.py`
# (`_RANGE_MONTHS`/`_subtract_months`/`_range_start`, `GET /valuations`).
# Świadomie **zduplikowane**, nie zaimportowane stamtąd: to prywatne
# (podkreślnikowe) funkcje innego modułu operujące na innej tabeli
# (`prices` tu, `portfolio_valuations` tam) — import przekraczałby granicę
# modułów po szczegół implementacyjny (skill `fastapi-modul`), a sama logika
# to kilka linijek arytmetyki na datach, nie wzór analityczny z listy
# „nie duplikuj" (skill `analityka-struktury` dotyczy wzoru wagi/HHI, nie
# tego). Jeśli te dwie kopie kiedyś się rozjadą, warto wydzielić wspólne
# `core/dates.py` — poza zakresem tego kroku (raportowane w podsumowaniu).
_RANGE_MONTHS: dict[str, int] = {"1M": 1, "3M": 3, "1Y": 12}


async def get_rate_pln(db: AsyncSession, currency: str, on_date: date) -> Decimal | None:
    """Kurs `currency` względem PLN obowiązujący w dniu `on_date`.

    Reguła CLAUDE.md #3.5: NBP nie publikuje kursu w weekendy/święta, więc
    zamiast wymagać dokładnego wpisu na `on_date`, cofamy się do
    **najnowszego notowania nie późniejszego niż `on_date`**
    (`max(date) <= D`) — stąd `ORDER BY date DESC LIMIT 1`, nie równość.

    Zwraca `None`, jeśli w `fx_rates` nie ma **żadnego** notowania
    `currency` w dniu `on_date` lub wcześniej (np. baza dopiero zasilana,
    albo literówka w kodzie waluty) — wołający (silnik wyceny, etap 5)
    decyduje, co z tym zrobić (błąd wyceny pozycji, nie cichy `0`).
    """
    stmt = (
        select(FxRate.rate_pln)
        .where(FxRate.currency == currency.upper(), FxRate.date <= on_date)
        .order_by(FxRate.date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_price(db: AsyncSession, asset_id: UUID, on_date: date) -> Price | None:
    """Notowanie `asset_id` obowiązujące w dniu `on_date`.

    Ta sama reguła `max(date) <= D` co `get_rate_pln` powyżej (`ORDER BY
    date DESC LIMIT 1`) — giełdy też nie notują w weekendy/święta. Zwraca
    **cały wiersz** `Price`, nie sam `close_adj`, bo wołający (silnik
    wyceny, `portfolio/service.py`, plan krok 26) musi znać `Price.date`,
    żeby ocenić, jak stara jest cena względem `on_date` — pozycja wyceniona
    ceną starszą niż żądany dzień jest oznaczana jako `stale` w odpowiedzi
    API (`GET /holdings`, `GET /summary`), nie liczona cicho jak świeża.

    Zwraca `None`, jeśli w `prices` nie ma **żadnego** notowania `asset_id`
    w dniu `on_date` lub wcześniej — dokładnie ten sam podział
    odpowiedzialności co `get_rate_pln`: `None` vs „stary wiersz” to dwa
    różne przypadki, oba obsługuje wołający, nie ta funkcja.
    """
    stmt = (
        select(Price)
        .where(Price.asset_id == asset_id, Price.date <= on_date)
        .order_by(Price.date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def detect_price_jump(
    db: AsyncSession, asset_id: UUID, on_date: date, *, threshold: Decimal = Decimal("0.40")
) -> bool:
    """Heurystyka wykrywania nieskorygowanego splitu (plan krok 28): `True`,
    jeśli surowe `close` skoczyło o więcej niż `threshold` (domyślnie 40%)
    między dwoma najnowszymi notowaniami `<= on_date`.

    Celowo `close`, nie `close_adj` — dostawcy (yfinance/Stooq) przeliczają
    `close_adj` retroaktywnie dla całej historii przy splicie, więc
    `close_adj` dnia splitu jest *ciągłe* względem dnia poprzedniego (skoku
    nie widać). To surowe `close` faktycznie skacze o współczynnik splitu w
    dniu zdarzenia, stąd heurystyka ma sens tylko na nim — CLAUDE.md #4
    (wycena zawsze na `close_adj`) dotyczy liczenia wartości portfela, nie
    tego sygnału ostrzegawczego. Wynik to tylko podpowiedź dla użytkownika
    „sprawdź liczbę sztuk” (bez rejestru transakcji ilość nie koryguje się
    sama po splicie, poza zakresem produktu — CLAUDE.md #1), nie automatyczna
    korekta.

    `False`, gdy nie da się ocenić: mniej niż dwa notowania w historii,
    którykolwiek z dwóch ma `close IS NULL` (kolumna nullable w modelu — nie
    każdy dostawca/dzień ją uzupełnia), albo starsze `close == 0` (w
    przeciwieństwie do `close_adj` nie ma tu `CHECK > 0`, więc dzielenie
    zabezpieczamy ręcznie) — brak danych to nie sygnał splitu.
    """
    stmt = (
        select(Price.close)
        .where(Price.asset_id == asset_id, Price.date <= on_date)
        .order_by(Price.date.desc())
        .limit(2)
    )
    result = await db.execute(stmt)
    closes = list(result.scalars().all())

    if len(closes) < 2:
        return False

    close_newer, close_older = closes
    if close_newer is None or close_older is None or close_older == 0:
        return False

    ratio = close_newer / close_older
    return abs(ratio - 1) > threshold


async def upsert_fx_rates(db: AsyncSession, quotes: list[FxQuote]) -> None:
    """Zapisuje `quotes` do `fx_rates`, idempotentnie (`ON CONFLICT (currency,
    date) DO UPDATE`) — ponowne uruchomienie ingestii NBP za ten sam zakres
    dat nadpisuje `rate_pln`, nie duplikuje wierszy.

    Uwaga: `quotes` to surowe kursy z dnia notowania — to **nie** jest
    miejsce na logikę `max(date) <= D` (to robi `get_rate_pln` przy
    odczycie, nie zapis: zapisujemy dokładnie te dni, które NBP faktycznie
    opublikował).
    """
    if not quotes:
        logger.info("marketdata.upsert_fx_rates.empty")
        return
    values = [
        {"currency": quote.currency.upper(), "date": quote.date, "rate_pln": quote.rate_pln}
        for quote in quotes
    ]
    stmt = insert(FxRate).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[FxRate.currency, FxRate.date],
        set_={"rate_pln": stmt.excluded.rate_pln},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("marketdata.upsert_fx_rates.done", count=len(values))


async def upsert_prices(
    db: AsyncSession, asset_id: UUID, bars: list[PriceBar], *, source: str | None = None
) -> None:
    """Zapisuje `bars` do `prices` dla `asset_id`, idempotentnie
    (`ON CONFLICT (asset_id, date) DO UPDATE`).

    Ogólna dla wszystkich providerów OHLCV (NBP/złoto dziś, Stooq/yfinance/
    Finnhub w kroku 22) — providerzy dostarczają `PriceBar`, ten moduł nie
    wie, skąd świeca pochodzi. Dlatego `source` (nazwa dostawcy) jest
    parametrem wołającego, a nie odczytem z `PriceBar`: to warstwa ingestii
    rozstrzyga łańcuch fallbacku i tylko ona wie, który dostawca faktycznie
    odpowiedział.

    `source` jest zapisywane także przy nadpisaniu istniejącego wiersza —
    jeśli dzień przyszedł wcześniej ze Stooqa, a dziś z yfinance, to od
    teraz pochodzi z yfinance i kolumna musi to odzwierciedlać. Zostawienie
    starej wartości dałoby serię, w której `source` kłamie o połowie
    wierszy — czyli gorzej niż brak kolumny (patrz `Price.source`).

    `source=None` oznacza „wołający nie podał źródła" i zostawia `NULL`,
    tak jak wiersze sprzed tej kolumny.

    Pilnuje CHECK `close_adj > 0` (baza i tak by odrzuciła cały `INSERT`,
    ale wolimy odsiać pojedynczy zepsuty wiersz z logiem niż stracić zapis
    całej reszty poprawnych dni w tym samym wywołaniu) — świece z
    `close_adj <= 0` są pomijane i logowane jako ostrzeżenie, nie wysyłane
    do bazy.
    """
    if not bars:
        logger.info("marketdata.upsert_prices.empty", asset_id=str(asset_id))
        return

    values = []
    for bar in bars:
        if bar.close_adj <= 0:
            logger.warning(
                "marketdata.upsert_prices.invalid_close_adj",
                asset_id=str(asset_id),
                date=bar.date.isoformat(),
                close_adj=str(bar.close_adj),
            )
            continue
        values.append(
            {
                "asset_id": asset_id,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "close_adj": bar.close_adj,
                "volume": bar.volume,
                "source": source,
            }
        )

    if not values:
        logger.warning("marketdata.upsert_prices.all_invalid", asset_id=str(asset_id))
        return

    stmt = insert(Price).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Price.asset_id, Price.date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "close_adj": stmt.excluded.close_adj,
            "volume": stmt.excluded.volume,
            "source": stmt.excluded.source,
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(
        "marketdata.upsert_prices.done",
        asset_id=str(asset_id),
        count=len(values),
        source=source,
    )


async def list_active_assets(db: AsyncSession, market_code: str) -> list[Asset]:
    """Aktywne aktywa notowane na `market_code`, posortowane po symbolu —
    lista do ingestii EOD (`worker/jobs/ingest_market.py`, plan krok 23).

    `is_active=False` (aktywo wygaszone, patrz `models.py`) jest pomijane —
    nie ma sensu odpytywać dostawców o coś, co już nie powinno być
    aktualizowane; historia w `prices` zostaje nietknięta.
    """
    stmt = (
        select(Asset)
        .where(Asset.market_code == market_code, Asset.is_active.is_(True))
        .order_by(Asset.symbol)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_fx_currencies(db: AsyncSession) -> list[str]:
    """Zbiór walut, dla których trzeba mieć kurs NBP — wyliczony z
    `assets.currency` (aktywnych aktywów), nie z osobnego słownika: rynek
    `FX` (`docs/slownik-rynkow.md`) sam w sobie nie ma żadnych wierszy
    `assets` (nie ma czego zmapować przez `asset_source_map` — kod waluty
    ISO jest już „symbolem" zrozumiałym bezpośrednio dla
    `DataProvider.get_fx`, nic tu nie trzeba tłumaczyć).

    `PLN` pomijane — wycena w PLN nie wymaga przeliczenia kursu (CLAUDE.md
    #3.5 dotyczy walut *obcych*).
    """
    stmt = (
        select(Asset.currency)
        .where(Asset.currency != "PLN", Asset.is_active.is_(True))
        .distinct()
        .order_by(Asset.currency)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_provider_symbol(db: AsyncSession, asset_id: UUID, provider: str) -> str | None:
    """Symbol aktywa u konkretnego dostawcy (`asset_source_map.provider_symbol`),
    albo `None`, jeśli brak mapowania dla tej pary `(asset_id, provider)`
    (plan krok 22, etap 4).

    Jedyne miejsce, w którym wolno odczytać symbol zewnętrzny przed
    wywołaniem `DataProvider.get_ohlcv`/`get_metadata` — zero sklejania
    symbolu w kodzie providera/serwisu (CLAUDE.md #3.4, SKILL
    `data-provider`, reguła 1: „Symbol zewnętrzny wyłącznie z
    `asset_source_map`").
    """
    stmt = select(AssetSourceMap.provider_symbol).where(
        AssetSourceMap.asset_id == asset_id,
        AssetSourceMap.provider == provider,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def search_assets(db: AsyncSession, query: str, *, limit: int = 20) -> list[Asset]:
    """Szuka `assets` po `symbol`/`name`, `ILIKE '%query%'` (case-insensitive,
    plan krok 24, etap 4).

    Tylko `is_active=True` — aktywa wygaszone (`is_active=False`, patrz
    docstring `Asset` w `models.py`) nadal istnieją dla historii `prices`/
    `holdings`, ale nie mają sensu jako wynik wyszukiwania „dodaj pozycję".
    `query` jest już zwalidowane przez `routes.py` (min. długość) — ta
    funkcja nie zna reguł walidacji wejścia HTTP, tylko wykonuje zapytanie.
    """
    pattern = f"%{query}%"
    stmt = (
        select(Asset)
        .where(
            Asset.is_active.is_(True),
            or_(Asset.symbol.ilike(pattern), Asset.name.ilike(pattern)),
        )
        .order_by(Asset.symbol)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_markets(db: AsyncSession) -> list[Market]:
    """Wszystkie rynki ze słownika `markets`, posortowane po `code` — bez
    `LIMIT`, tabela ma kilkanaście wierszy (ADR-102), nie rośnie z ruchem
    użytkowników.
    """
    result = await db.execute(select(Market).order_by(Market.code))
    return list(result.scalars().all())


async def get_market(db: AsyncSession, code: str) -> Market | None:
    """Lookup pojedynczego rynku po kluczu naturalnym (`markets.code`) —
    podstawa `GET /markets/{code}/index` (krok 30): `service.py` mapuje
    `None` na `NotFoundError` (rynek nieznany), routing nie zna tego
    rozróżnienia (skill `fastapi-modul`)."""
    return await db.get(Market, code)


async def list_markets_by_codes(db: AsyncSession, codes: list[str]) -> list[Market]:
    """Rynki dla zbioru kodów w jednym zapytaniu (nie N+1) — używane przez
    `analytics.service.market_ranking` (krok 30) do dociągnięcia `name`/
    `index_asset_id` dla każdego rynku obecnego w wycenionym portfelu.
    Pusta `codes` → pusta lista bez odpytywania bazy."""
    if not codes:
        return []
    stmt = select(Market).where(Market.code.in_(codes))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_asset(db: AsyncSession, asset_id: UUID) -> Asset | None:
    """Lookup po kluczu głównym `assets.id`.

    Duplikuje (celowo, jeden `db.get`) `portfolio.repository.get_asset` —
    ten moduł jest właścicielem modelu `Asset`, więc lookup po PK ma tu
    naturalny dom; `portfolio.repository.get_asset` zostaje nietknięty
    (używany przy tworzeniu/wycenie pozycji), żeby nie robić cross-module
    refaktoru poza zakresem kroku 30. Konsument: `analytics.service.
    _index_snapshot` (indeks referencyjny rynku, `symbol`/`id` do
    odpowiedzi `GET /portfolios/{id}/markets`)."""
    return await db.get(Asset, asset_id)


async def get_asset_by_symbol(db: AsyncSession, symbol: str) -> Asset | None:
    """Lookup po `assets.symbol` (indeks `ix_assets_symbol`).

    Konsument: `analytics.service._benchmark_series` (krok 42) — benchmark
    jest w kontrakcie API identyfikowany symbolem, nie UUID-em, bo jego
    identyfikator wpisuje się w URL (`?benchmark=^GSPC`) i musi być czytelny.
    """
    stmt = select(Asset).where(Asset.symbol == symbol).limit(1)
    return (await db.execute(stmt)).scalars().first()


async def get_latest_prices(
    db: AsyncSession, asset_id: UUID, *, limit: int, on_date: date | None = None
) -> list[Price]:
    """Ostatnie `limit` notowań `asset_id`, malejąco po dacie (najnowsze
    pierwsze) — jedno zapytanie obsługuje zarówno zmianę d/d (dwa pierwsze
    elementy), jak i mini-serię `series_30d` (`limit=30`, wołający odwraca
    kolejność na rosnącą) w `analytics.service._index_snapshot` (krok 30,
    ADR-102). Mniej niż `limit` wierszy w historii → krótsza lista, nie błąd
    (indeks świeżo dodany do słownika może mieć niepełną historię EOD).

    `on_date` obcina serię do notowań **obowiązujących w tym dniu** (`date <=
    on_date`), tak samo jak `get_latest_price` wyżej. Wołający wyceniający
    portfel na konkretny dzień MUSI je podać: `worker/jobs/snapshot_portfolios.py`
    liczy wycenę za `run_date` z przeszłości, a bez tego filtra dostałby zmianę
    d/d policzoną z najnowszych notowań w całej bazie — czyli z przyszłości
    względem wycenianego dnia. Domyślne `None` (bez filtra) zostaje dla
    `analytics.service._index_snapshot`, gdzie ranking rynków z definicji
    pokazuje stan bieżący i nie ma wariantu historycznego."""
    stmt = select(Price).where(Price.asset_id == asset_id)
    if on_date is not None:
        stmt = stmt.where(Price.date <= on_date)
    stmt = stmt.order_by(Price.date.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _subtract_months(d: date, months: int) -> date:
    """Patrz `portfolio/repository._subtract_months` — sama logika,
    zduplikowana świadomie (patrz komentarz przy `_RANGE_MONTHS` wyżej)."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _range_start(range_: str, today: date) -> date | None:
    """Patrz `portfolio/repository._range_start` — `None` dla `max` (cała
    historia dostępna w `prices`)."""
    if range_ == "YTD":
        return date(today.year, 1, 1)
    if range_ == "max":
        return None
    return _subtract_months(today, _RANGE_MONTHS[range_])


async def list_prices_in_range(
    db: AsyncSession, asset_id: UUID, *, range_: str, today: date
) -> list[Price]:
    """Seria `prices` dla `asset_id` w `range_`, rosnąco po dacie — podstawa
    `GET /markets/{code}/index?range=` (krok 30). Ten sam kształt zakresu co
    `portfolio.repository.list_valuations`, tylko na tabeli `prices` zamiast
    `portfolio_valuations`."""
    start = _range_start(range_, today)
    stmt = select(Price).where(Price.asset_id == asset_id)
    if start is not None:
        stmt = stmt.where(Price.date >= start)
    stmt = stmt.order_by(Price.date.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_prices_with_carry(
    db: AsyncSession, asset_id: UUID, *, start: date, end: date
) -> list[Price]:
    """Notowania `asset_id` w `[start, end]` **plus ostatnie sprzed `start`**,
    rosnąco po dacie (plan krok 42, benchmark).

    Ta dokładka to `max(date) <= D` z `get_rate_pln`/`get_latest_price`
    przeniesione na całą serię naraz. Benchmark trzeba wyrównać do dat
    snapshotów portfela, a te nie muszą pokrywać się z sesjami giełdowymi:
    portfel ma snapshot z poniedziałku będącego świętem na GPW, benchmark
    ostatnie notowanie z piątku. Bez wiersza sprzed `start` pierwszy punkt
    porównania wypadałby zawsze, gdy okno zaczyna się w dniu bez sesji —
    a to jest dzień, w którym normalizujemy obie serie do 100.

    Jedno zapytanie zamiast N+1 po dacie: przy pięcioletnim `range=max`
    (1300 snapshotów) pętla z `get_latest_price` per dzień dałaby 1300 zapytań
    na jedno żądanie HTTP. Wyrównanie robi `analytics.benchmark.as_of_values`
    na już pobranej liście.
    """
    carry = (
        select(func.max(Price.date))
        .where(Price.asset_id == asset_id, Price.date < start)
        .scalar_subquery()
    )
    stmt = (
        select(Price)
        .where(
            Price.asset_id == asset_id,
            Price.date <= end,
            Price.date >= func.coalesce(carry, start),
        )
        .order_by(Price.date.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_fx_rates_with_carry(
    db: AsyncSession, currency: str, *, start: date, end: date
) -> list[FxRate]:
    """Kursy `currency` w `[start, end]` plus ostatni sprzed `start`, rosnąco.

    Odpowiednik `list_prices_with_carry` dla tabeli `fx_rates` — benchmark
    w walucie obcej (`^GSPC` w USD) musi zostać przeliczony na PLN kursem NBP
    (decyzja 4 planu etapu 8, CLAUDE.md #3.5), a NBP nie publikuje tabel
    w weekendy i święta.
    """
    carry = (
        select(func.max(FxRate.date))
        .where(FxRate.currency == currency.upper(), FxRate.date < start)
        .scalar_subquery()
    )
    stmt = (
        select(FxRate)
        .where(
            FxRate.currency == currency.upper(),
            FxRate.date <= end,
            FxRate.date >= func.coalesce(carry, start),
        )
        .order_by(FxRate.date.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def count_prices_in_range(db: AsyncSession, asset_id: UUID, *, start: date, end: date) -> int:
    """Liczba wierszy `prices` dla `asset_id` w `[start, end]` (włącznie).

    Istnieje po to, żeby backfill (`worker/jobs/ingest_market.py`) raportował
    **ile danych faktycznie leży w bazie**, a nie ile razy dostawca
    odpowiedział. Dostawca potrafi zwrócić pustą listę bez błędu (aktywo nie
    istniało jeszcze w tym okresie, święto, wycofanie z obrotu), a wtedy
    `upsert_prices` też kończy się sukcesem — licznik oparty na odpowiedziach
    pokazywałby komplet tam, gdzie nie ma ani jednego notowania.
    """
    stmt = (
        select(func.count())
        .select_from(Price)
        .where(Price.asset_id == asset_id, Price.date >= start, Price.date <= end)
    )
    return int((await db.execute(stmt)).scalar_one())


async def count_fx_rates_in_range(
    db: AsyncSession, currency: str, *, start: date, end: date
) -> int:
    """Odpowiednik `count_prices_in_range` dla `fx_rates` (patrz jego docstring)."""
    stmt = (
        select(func.count())
        .select_from(FxRate)
        .where(
            FxRate.currency == currency.upper(),
            FxRate.date >= start,
            FxRate.date <= end,
        )
    )
    return int((await db.execute(stmt)).scalar_one())


@dataclass(frozen=True, slots=True)
class PriceSeriesDiagnostics:
    """Stan serii `prices` jednego aktywa w zadanym zakresie — na tyle, żeby
    odpowiedzieć na pytanie „czy tej serii wolno używać do liczenia zwrotów".

    `close_adj` nie ma jednej konwencji między dostawcami: yfinance zwraca
    prawdziwą cenę skorygowaną o dywidendy i splity (`close_adj != close`),
    a Stooq/Finnhub/Binance ustawiają `close_adj := close`, bo korekty nie
    mają. Zszycie obu w jednej serii daje skok w miejscu styku, niewidoczny
    w surowym `close` i nie do odróżnienia od prawdziwego ruchu ceny —
    a wycena i wykresy idą po `close_adj` (CLAUDE.md #3.4).

    **Konwencji NIE da się wyczytać z relacji `close_adj` do `close`** —
    dlatego rozstrzyga `source`, nie liczniki. Współczynnik korekty jest
    z definicji równy 1 dla ogona serii (po ostatniej dywidendzie/splicie
    nie ma czego korygować), więc każda seria yfinance ma na końcu wiersze
    z `close_adj == close`. Pierwsza wersja tej klasy blokowała na
    „są jedne i drugie" i zapalała się na KAŻDEJ czystej serii yfinance:
    AAPL 1252/2, MSFT 1198/56, CDR 969/280 — same wyniki jednego przebiegu
    z `--provider yfinance`. Liczniki zostają jako informacja diagnostyczna
    („czy ta seria w ogóle jest korygowana"), nie jako kryterium blokady.
    """

    rows: int
    adjusted_rows: int
    unadjusted_rows: int
    sources: tuple[str | None, ...]

    @property
    def mixed_sources(self) -> bool:
        """Seria pochodzi z więcej niż jednego źródła — jedyny wiarygodny
        sygnał wymieszanej konwencji (patrz docstring klasy).

        `None` (wiersze sprzed kolumny `source`, migracja `926b382d1715`)
        liczy się jako osobna wartość, bo jest nieznanego pochodzenia:
        seria pół-NULL, pół-yfinance może być mieszanką i nie ma jak tego
        rozstrzygnąć. Dwóch dostawców o tej samej konwencji zapali się tu
        niepotrzebnie — to fałszywy alarm w bezpieczną stronę, a naprawa
        jest ta sama i tania (pobrać zakres ponownie z `--provider`).
        """
        return len(set(self.sources)) > 1


async def price_series_diagnostics(
    db: AsyncSession, asset_id: UUID, *, start: date, end: date
) -> PriceSeriesDiagnostics:
    """Diagnostyka serii `prices` dla `asset_id` w `[start, end]` (włącznie).

    Dwa zapytania zamiast jednego, bo `DISTINCT` po `source` nie składa się z
    agregatami zliczającymi w tym samym `SELECT`.
    """
    stmt = select(
        func.count(),
        func.count().filter(Price.close.is_not(None), Price.close_adj != Price.close),
        func.count().filter(Price.close.is_not(None), Price.close_adj == Price.close),
    ).where(Price.asset_id == asset_id, Price.date >= start, Price.date <= end)
    rows, adjusted, unadjusted = (await db.execute(stmt)).one()

    sources_stmt = (
        select(Price.source)
        .where(Price.asset_id == asset_id, Price.date >= start, Price.date <= end)
        .distinct()
        .order_by(Price.source)
    )
    sources = tuple((await db.execute(sources_stmt)).scalars().all())

    return PriceSeriesDiagnostics(
        rows=int(rows),
        adjusted_rows=int(adjusted),
        unadjusted_rows=int(unadjusted),
        sources=sources,
    )


async def get_latest_price_date_for_assets(db: AsyncSession, asset_ids: list[UUID]) -> date | None:
    """`MAX(prices.date)` dla zbiór `asset_ids` — podstawa `eod_marker`
    (segment „data EOD" klucza cache Redis, CLAUDE.md #3.7, plan krok 31).

    Decyzja (raportowana w podsumowaniu zadania kroku 31): licząc marker z
    `MAX(date)` **tylko** aktywów faktycznie trzymanych w danym portfelu
    (nie przez `ingestion_runs.market_code`), unikamy JOIN-a przez rynek i
    nie przejmujemy się świeżością rynków, na których użytkownik nie jest
    zainwestowany — bezpośrednio odpowiada pytaniu „czy dla TEGO portfela
    przyszły nowe dane EOD".

    Pusta `asset_ids` (portfel bez pozycji) → `None` bez odpytywania bazy;
    `None` też, gdy żadne z `asset_ids` nie ma jeszcze wiersza w `prices`
    (świeżo dodane aktywo, worker EOD jeszcze nie zaciągnął danych) —
    wołający (`analytics.service._eod_marker`) mapuje `None` na
    deterministyczny marker `"none"`, nigdy nie crashuje."""
    if not asset_ids:
        return None
    stmt = select(func.max(Price.date)).where(Price.asset_id.in_(asset_ids))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def price_marker_for_asset(db: AsyncSession, asset_id: UUID) -> tuple[date | None, int]:
    """`MAX(prices.date)` **i** `COUNT(*)` dla jednego aktywa — segment klucza
    cache serii benchmarku (krok 42).

    **`MAX(date)` samo nie wystarczy**, dokładnie z tego powodu co przy
    `portfolio.repository.valuations_marker`: notowania benchmarku przybywają
    też **wstecz**. `make backfill` dopisuje ETFBW20TR.WA ponad tysiąc sesji
    historii, nie ruszając maksimum — dzisiejszy wiersz zwykle już jest.
    Marker oparty na samym maksimum dałby po takim przebiegu trafienie
    w cache z odpowiedzią policzoną z krótszej serii, a w skrajnym przypadku
    z `unavailable_reason` („brak notowań na dzień startu lub wcześniej")
    wiszącym do wygaśnięcia sześciogodzinnego TTL, mimo że historia już jest.

    Odróżnione od `get_latest_price_date_for_assets`, które pilnuje danych
    portfela — tam wiersze przyrastają wyłącznie od najnowszej strony, więc
    `MAX` wystarcza i dokładanie `COUNT(*)` po całym koszyku aktywów byłoby
    kosztem bez pokrycia.
    """
    stmt = select(func.max(Price.date), func.count()).where(Price.asset_id == asset_id)
    latest, count = (await db.execute(stmt)).one()
    return latest, count


async def get_latest_fx_rate_date(db: AsyncSession, currency: str) -> date | None:
    """`MAX(fx_rates.date)` dla waluty — druga połowa markera benchmarku
    notowanego poza PLN (krok 42).

    Bez niej klucz cache nie widzi nowego kursu NBP przy niezmienionych
    notowaniach, a to jest stan codzienny, nie skrajny: NBP publikuje tabelę
    ok. 12:00, notowania `^GSPC` przychodzą z ingestii wieczorem. Ostatni
    punkt serii siedziałby wtedy na wczorajszym kursie do wygaśnięcia TTL.
    """
    stmt = select(func.max(FxRate.date)).where(FxRate.currency == currency)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_latest_ingestion_runs(db: AsyncSession) -> dict[str, IngestionRun]:
    """Ostatni `IngestionRun` (po `started_at DESC`) per `market_code`,
    w jednym zapytaniu (`DISTINCT ON`, Postgres) zamiast N+1 — podstawa
    `GET /meta/freshness`.

    Rynki bez żadnego przebiegu ingestii po prostu nie mają klucza w
    zwróconym słowniku (wołający, `service.get_markets_freshness`, traktuje
    to jako „świeżość nieznana", nie błąd).
    """
    stmt = (
        select(IngestionRun)
        .distinct(IngestionRun.market_code)
        .order_by(IngestionRun.market_code, IngestionRun.started_at.desc())
    )
    result = await db.execute(stmt)
    return {run.market_code: run for run in result.scalars().all()}


async def upsert_reference_rates(
    db: AsyncSession,
    rates: list[ReferenceRate],
    *,
    source: str,
    fetched_at: datetime,
) -> int:
    """Zapisuje historię stopy referencyjnej NBP idempotentnie.

    `ON CONFLICT (effective_from) DO UPDATE` — job tygodniowy pobiera za
    każdym razem pełne archiwum (jedno żądanie, ~96 wierszy), więc
    przytłaczająca większość wierszy to powtórka. Zwraca liczbę zapisanych
    wierszy, żeby job miał co zalogować.
    """
    if not rates:
        logger.info("marketdata.upsert_reference_rates.empty")
        return 0
    values = [
        {
            "effective_from": rate.effective_from,
            "rate": rate.rate,
            "source": source,
            "fetched_at": fetched_at,
        }
        for rate in rates
    ]
    stmt = insert(NbpReferenceRate).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NbpReferenceRate.effective_from],
        set_={
            "rate": stmt.excluded.rate,
            "source": stmt.excluded.source,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("marketdata.upsert_reference_rates.done", count=len(values))
    return len(values)


async def get_reference_rate(db: AsyncSession, on_date: date) -> Decimal | None:
    """Stopa referencyjna NBP obowiązująca w dniu `on_date` (ułamek roczny).

    `max(effective_from) <= D`, dokładnie jak `get_rate_pln` dla kursów
    (CLAUDE.md #3.5) — z tą różnicą, że tu „cofanie się" nie jest obejściem
    weekendu, tylko istotą danej: stopa obowiązuje od decyzji RPP do
    następnej decyzji.

    Zwraca `None`, gdy `on_date` jest wcześniejsza niż pierwszy wpis w
    archiwum (NBP publikuje od 1998-02-26) albo gdy tabela jest jeszcze
    pusta. Wołający (Sharpe, krok 41b) ma wtedy **nie liczyć** wskaźnika,
    a nie podstawiać zero — zero jest wartością tak samo prawdopodobną jak
    każda inna i milcząco zmieniłoby wynik.
    """
    stmt = (
        select(NbpReferenceRate.rate)
        .where(NbpReferenceRate.effective_from <= on_date)
        .order_by(NbpReferenceRate.effective_from.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reference_rates(
    db: AsyncSession, *, start: date, end: date
) -> list[NbpReferenceRate]:
    """Zmiany stopy obowiązujące w `[start, end]`, wraz z tą sprzed `start`.

    Sharpe na serii dziennej potrzebuje stopy dla **każdego** dnia okresu,
    a nie tylko dla dni, w których RPP coś zmieniła. Wpis obowiązujący na
    początku okresu prawie nigdy nie ma `effective_from == start`, więc
    zapytanie zawężone do `[start, end]` zostawiłoby początek serii bez
    stopy. Stąd dociągamy jeden wiersz wstecz i wołający robi lokalny
    lookup `max(effective_from) <= D` po tej liście — jedno zapytanie na
    cały okres zamiast jednego na dzień.
    """
    boundary = (
        select(func.max(NbpReferenceRate.effective_from))
        .where(NbpReferenceRate.effective_from <= start)
        .scalar_subquery()
    )
    stmt = (
        select(NbpReferenceRate)
        .where(
            NbpReferenceRate.effective_from <= end,
            or_(
                NbpReferenceRate.effective_from >= start,
                NbpReferenceRate.effective_from == boundary,
            ),
        )
        .order_by(NbpReferenceRate.effective_from)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_latest_reference_rate_date(db: AsyncSession) -> date | None:
    """Najnowsze `effective_from` w tabeli — podstawa oceny świeżości.

    Świeżość liczymy **z tej daty**, nigdy z `data_publikacji` w XML-u NBP,
    który jest zamrożony na 2015 roku (patrz `providers/nbp_rates`).
    """
    stmt = select(func.max(NbpReferenceRate.effective_from))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
