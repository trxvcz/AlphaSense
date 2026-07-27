"""Job EOD: ingestia cen/kursów dla jednego rynku (plan krok 23, etap 4).

Wołany albo przez harmonogram (`worker/scheduler.py`, APScheduler, o
godzinie z `markets.eod_time`), albo ręcznie (`python -m app.cli ingest
--market <code>`, `app/cli.py`) — oba wejścia wołają dokładnie tę samą
funkcję `ingest_market`, żeby manualne triggerowanie było wiarygodną
weryfikacją tego, co faktycznie zrobi harmonogram (SKILL `job-eod`).

**Dlaczego dwie osobne sesje (`lock_session`/`db`):** `advisory_lock`
(`app/db/advisory_lock.py`) wymaga, żeby wzięcie i zwolnienie blokady
wykonały się na tym samym fizycznym połączeniu Postgresa; `upsert_prices`/
`upsert_fx_rates` robią własny `commit()` per wywołanie, co mogłoby oddać
połączenie do poola w trakcie trwania blokady, jeśli użyć tej samej sesji do
obu rzeczy (patrz docstring `advisory_lock`, sekcja „Ważne dla wołających").
Dlatego `lock_session` istnieje wyłącznie po to, żeby trzymać blokadę
(żadnych innych zapytań), a cała właściwa praca (odczyt aktywów, wywołania
dostawców, zapisy, `ingestion_runs`) idzie przez oddzielną sesję `db`.

**Brak wspólnego symbolu dla całego łańcucha (OHLCV):** `FallbackChain`
(krok 20, `providers/fallback_chain.py`) przyjmuje jeden symbol dla
wszystkich dostawców po kolei — poprawne, gdy symbol jest uniwersalny (kod
waluty ISO, `get_fx`, patrz `_ingest_currency_fx` niżej), ale nie dla OHLCV:
różni dostawcy mają różny symbol tego samego aktywa (`cdr` na Stooq vs
`CDR.WA` na yfinance, CLAUDE.md #4 zasada 4 — „Symbol zewnętrzny nigdy nie
jest sklejany w kodzie"). Dlatego OHLCV nie woła `FallbackChain.get_ohlcv`
wprost — `_ingest_asset_ohlcv` niżej to per-aktywo odpowiednik
`FallbackChain._try_chain`, który tłumaczy symbol osobno przy każdej próbie
kolejnego dostawcy (`get_provider_symbol`), zamiast raz dla całego łańcucha.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProviderUnavailableError
from app.db.advisory_lock import advisory_lock
from app.db.session import AsyncSessionLocal
from app.modules.marketdata.models import Asset, IngestionRun, Market
from app.modules.marketdata.providers.base import Capability
from app.modules.marketdata.providers.guarded import Guarded
from app.modules.marketdata.repository import (
    get_provider_symbol,
    list_active_assets,
    list_fx_currencies,
    upsert_fx_rates,
    upsert_prices,
)
from app.modules.marketdata.service import build_fallback_chain
from worker.jobs.snapshot_portfolios import snapshot_portfolios

logger = structlog.get_logger(__name__)

# Zakres pobierany co przebieg — kilka dni wstecz, nie tylko `run_date`:
# ceny/kursy bywają publikowane z opóźnieniem (dostawca ma jeszcze braki
# dzień po sesji), albo `run_date` trafia na święto i trzeba dociągnąć
# najbliższy poprzedni dzień roboczy przy tym samym przebiegu, nie dopiero
# następnego dnia. Nadpisanie już zapisanych dni jest tanie i bezpieczne
# (`upsert_*`, `ON CONFLICT DO UPDATE`, CLAUDE.md #9) — nadgorliwość tutaj
# nie kosztuje poprawności.
_LOOKBACK_DAYS = 5

_STATUS_OK = "ok"
_STATUS_PARTIAL = "partial"
_STATUS_FAILED = "failed"

# Rynek bez żadnych `assets` w naszym słowniku (FX — kursy walut nie są
# reprezentowane jako `assets`, patrz `repository.list_fx_currencies`) —
# jedyny dziś, ale zestaw, nie `==`, żeby dodanie drugiego takiego rynku w
# przyszłości było zmianą jednej linii, nie rozgałęzieniem `if`.
_CURRENCY_MARKETS = frozenset({"FX"})


async def ingest_market(market_code: str, run_date: date | None = None) -> str | None:
    """Ingestia EOD dla `market_code` — punkt wejścia joba (patrz docstring
    modułu).

    `run_date=None` (domyślne, wołanie ze schedulera) liczy „dziś" w
    strefie czasowej **rynku** (`markets.timezone`), nie serwera — istotne
    dla rynków, których `eod_time` lokalny wypada blisko/po północy UTC
    (np. `US`, `America/New_York`, `eod_time` 23:15 lokalnie to już kolejny
    dzień kalendarzowy UTC w części roku), gdzie „dziś UTC" i „dziś rynku"
    mogłyby się różnić o jeden dzień.

    Zwraca ostateczny `status` przebiegu (`"ok"`/`"partial"`/`"failed"`) —
    albo `None`, gdy nic się nie wydarzyło (nieznany rynek, blokada zajęta
    przez inny proces). Scheduler nie używa zwrotki (APScheduler i tak tylko
    woła funkcję), ale `app/cli.py ingest` przekłada `"failed"` na niezerowy
    exit code do skryptów/CI (SKILL `job-eod`, sekcja „Diagnostyka").
    """
    async with AsyncSessionLocal() as lookup_db:
        market = await lookup_db.get(Market, market_code)
    if market is None:
        logger.error("ingest_market.unknown_market", market_code=market_code)
        return None

    effective_date = run_date or datetime.now(ZoneInfo(market.timezone)).date()
    lock_key = f"eod:{market_code}:{effective_date.isoformat()}"

    logger.info(
        "ingest_market.starting", market_code=market_code, run_date=effective_date.isoformat()
    )

    async with AsyncSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key=lock_key) as acquired:
            if not acquired:
                logger.info(
                    "ingest_market.lock_not_acquired",
                    market_code=market_code,
                    run_date=effective_date.isoformat(),
                )
                return None

            async with AsyncSessionLocal() as db:
                status = await _run_ingestion(db, market_code=market_code, run_date=effective_date)

    # Snapshot portfeli *po* zwolnieniu blokady rynku (już poza blokiem
    # `advisory_lock`/`async with lock_session`), nie w środku — snapshot ma
    # własną blokadę doradczą (`snapshot:{run_date}`, patrz
    # `worker/jobs/snapshot_portfolios.py`) i nie powinien trzymać blokady
    # rynku przez cały czas swojej pracy (SKILL `job-eod`: „snapshot
    # uruchamiany po ingestii, nie równolegle”). Wołany niezależnie od
    # `status` — nawet `"partial"`/`"failed"` ingestii tego rynku: silnik
    # wyceny liczy na ostatnich znanych cenach (`max(date) <= D`), więc
    # snapshot i tak ma sens, tylko ewentualnie na starszych danych.
    await snapshot_portfolios(run_date=effective_date)
    return status


async def _run_ingestion(db: AsyncSession, *, market_code: str, run_date: date) -> str:
    """Robi właściwą pracę pod już wziętą blokadą: pobiera aktywa/waluty
    rynku, próbuje dostawców z `build_fallback_chain(market_code)` per
    aktywo/waluta, zapisuje wyniki i na końcu jeden wiersz `IngestionRun`
    (SKILL `job-eod`, reguła 5) — niezależnie od tego, ile pojedynczych
    aktywów zawiodło (reguła 6: „job nie przerywa się na pierwszym błędzie
    aktywa"). Zwraca zapisany `status`.
    """
    started_at = datetime.now(UTC)

    try:
        chain = build_fallback_chain(market_code)
        start = run_date - timedelta(days=_LOOKBACK_DAYS)

        errors: dict[str, str] = {}
        provider_counts: Counter[str] = Counter()

        if market_code in _CURRENCY_MARKETS:
            currencies = await list_fx_currencies(db)
            assets_total = len(currencies)
            for currency in currencies:
                try:
                    provider_name = await _ingest_currency_fx(
                        db, currency, chain, start=start, end=run_date
                    )
                except Exception as exc:
                    errors[currency] = f"{type(exc).__name__}: {exc}"
                    logger.error(
                        "ingest_market.currency_failed",
                        market_code=market_code,
                        currency=currency,
                        error=errors[currency],
                    )
                    continue
                provider_counts[provider_name] += 1
        else:
            assets = await list_active_assets(db, market_code)
            assets_total = len(assets)
            for asset in assets:
                try:
                    provider_name = await _ingest_asset_ohlcv(
                        db, asset, chain, start=start, end=run_date
                    )
                except Exception as exc:
                    errors[asset.symbol] = f"{type(exc).__name__}: {exc}"
                    logger.error(
                        "ingest_market.asset_failed",
                        market_code=market_code,
                        asset_id=str(asset.id),
                        symbol=asset.symbol,
                        error=errors[asset.symbol],
                    )
                    continue
                provider_counts[provider_name] += 1
    except Exception as exc:
        # Porażka POZA pętlą per-aktywo/waluta (np. `build_fallback_chain`
        # nie rozpoznaje rynku mimo że wiersz w `markets` istnieje, albo
        # baza odmawia połączenia przy `list_active_assets`) — bez tego
        # `except` przebieg kończyłby się bez ŻADNEGO wiersza w
        # `ingestion_runs`, wbrew SKILL `job-eod` regule 5 („każdy
        # przebieg = wpis"): `/meta/freshness` pokazywałby wtedy stary
        # `last_run_at` zamiast świeżego `status=failed`, czyli dokładnie
        # ten przypadek, przed którym ostrzega SKILL („bez tego nie
        # wiadomo, czy dane są świeże"). Zapisujemy skromny wiersz i
        # re-raise'ujemy — scheduler/wołający nadal ma wyjątek do
        # zaalarmowania (Sentry w etapie 7).
        run = IngestionRun(
            market_code=market_code,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            provider="unknown",
            assets_total=0,
            assets_ok=0,
            status=_STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        db.add(run)
        await db.commit()
        logger.error(
            "ingest_market.crashed",
            market_code=market_code,
            run_date=run_date.isoformat(),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    assets_ok = sum(provider_counts.values())
    finished_at = datetime.now(UTC)

    if not errors:
        status = _STATUS_OK
    elif assets_ok:
        status = _STATUS_PARTIAL
    else:
        status = _STATUS_FAILED

    # Więcej niż jeden dostawca mógł faktycznie odpowiedzieć w jednym
    # przebiegu (np. część aktywów GPW przez Stooq, jedno przez yfinance po
    # porażce Stooq) — `ingestion_runs.provider` to pojedyncza kolumna
    # tekstowa, więc łączymy wszystkich, którzy odpowiedzieli, w
    # deterministycznej (posortowanej) kolejności. Jeśli nikt nie
    # odpowiedział (0 aktywów/walut albo same porażki), zapisujemy
    # pierwszego z łańcucha — informacja, kogo w ogóle próbowaliśmy.
    provider_field = "+".join(sorted(provider_counts)) if provider_counts else chain[0].name

    error_field = "; ".join(f"{key}: {msg}" for key, msg in errors.items()) if errors else None

    run = IngestionRun(
        market_code=market_code,
        started_at=started_at,
        finished_at=finished_at,
        provider=provider_field,
        assets_total=assets_total,
        assets_ok=assets_ok,
        status=status,
        error=error_field,
    )
    db.add(run)
    await db.commit()

    log_fields: dict[str, object] = {
        "market_code": market_code,
        "run_date": run_date.isoformat(),
        "assets_total": assets_total,
        "assets_ok": assets_ok,
        "status": status,
        "provider": provider_field,
    }
    if status == _STATUS_OK:
        logger.info("ingest_market.finished", **log_fields)
    else:
        # Porażka całości (status=failed) albo częściowa (status=partial)
        # to sygnał operacyjny — SKILL `job-eod` reguła 6: „niepowodzenie
        # całości = alert" (Sentry podłączony dopiero w etapie 7; do tego
        # czasu `structlog.error`/`warning` jest jedynym kanałem).
        logger.error("ingest_market.finished_with_errors", **log_fields)

    return status


async def _ingest_asset_ohlcv(
    db: AsyncSession,
    asset: Asset,
    chain: list[Guarded],
    *,
    start: date,
    end: date,
) -> str:
    """Próbuje dostawców `chain` po kolei dla `asset`, tłumacząc symbol
    osobno dla każdego (patrz docstring modułu, sekcja „Brak wspólnego
    symbolu"). Zwraca nazwę dostawcy, który faktycznie odpowiedział, po
    zapisaniu wyniku (`upsert_prices`).

    Dostawca bez mapowania w `asset_source_map` dla tego aktywa jest po
    prostu pomijany (nie liczy się jako porażka — nie było czego próbować),
    tak samo jak dostawca bez `Capability.OHLCV` w łańcuchu.
    """
    errors: dict[str, str] = {}
    for provider in chain:
        if Capability.OHLCV not in provider.supports:
            continue
        symbol = await get_provider_symbol(db, asset.id, provider.name)
        if symbol is None:
            continue
        try:
            bars = await provider.get_ohlcv(symbol, start, end)
        except Exception as exc:
            errors[provider.name] = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "ingest_market.asset_provider_failed",
                asset_id=str(asset.id),
                symbol=asset.symbol,
                provider=provider.name,
                error=errors[provider.name],
            )
            continue
        await upsert_prices(db, asset.id, bars)
        return provider.name

    raise ProviderUnavailableError(
        f"Brak dostępnego dostawcy OHLCV dla aktywa {asset.symbol!r} (rynek {asset.market_code!r})",
        details={"asset_id": str(asset.id), "symbol": asset.symbol, "errors": errors},
    )


async def _ingest_currency_fx(
    db: AsyncSession,
    currency: str,
    chain: list[Guarded],
    *,
    start: date,
    end: date,
) -> str:
    """Odpowiednik `_ingest_asset_ohlcv` dla `Capability.FX` — kod waluty
    ISO jest tym samym „symbolem" dla każdego dostawcy w łańcuchu (żadne
    tłumaczenie przez `asset_source_map` nie jest tu potrzebne, patrz
    `repository.list_fx_currencies`), więc w odróżnieniu od OHLCV można
    bezpiecznie użyć jednego symbolu dla całego łańcucha.
    """
    errors: dict[str, str] = {}
    for provider in chain:
        if Capability.FX not in provider.supports:
            continue
        try:
            quotes = await provider.get_fx(currency, start, end)
        except Exception as exc:
            errors[provider.name] = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "ingest_market.currency_provider_failed",
                currency=currency,
                provider=provider.name,
                error=errors[provider.name],
            )
            continue
        await upsert_fx_rates(db, quotes)
        return provider.name

    raise ProviderUnavailableError(
        f"Brak dostępnego dostawcy FX dla waluty {currency!r}",
        details={"currency": currency, "errors": errors},
    )


__all__ = ["ingest_market"]
