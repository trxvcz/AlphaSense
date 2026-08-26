"""Job EOD: snapshot wyceny wszystkich portfeli do `portfolio_valuations`
(plan krok 27, etap 5).

Wołany na końcu `ingest_market` (`worker/jobs/ingest_market.py`), *po*
zwolnieniu blokady rynku, nie równolegle z ingestią (SKILL `job-eod`,
sekcja „Kolejność dobowa”) — a więc faktycznie **cztery razy dziennie**,
raz po każdym rynku (NBP/GPW/US/CRYPTO). To zamierzone: silnik wyceny
(`portfolio_service.current_value`) czyta ceny/kursy przez `max(date) <= D`
(CLAUDE.md #3.5), więc każdy kolejny przebieg tego samego dnia po prostu
dokłada świeższe dane dla portfeli trzymających aktywa z tego rynku, a
`upsert_valuation` jest idempotentny (`ON CONFLICT DO UPDATE`, CLAUDE.md
#3.9) — nadpisuje, nie duplikuje. Jeśli kursów NBP jeszcze brakuje (job NBP
jeszcze nie wystartował/zawiódł), snapshot i tak powstaje na ostatnim
znanym kursie; pozycja bez żadnego kursu/ceny jest po prostu pominięta w
sumie (`PortfolioValue.total_pln`, patrz `portfolio/service.py`), nie
liczona jako zero.

**Dlaczego dwie sesje (`lock_session`/`db`)**: identyczny powód co
`ingest_market` (patrz docstring tamtego modułu, sekcja „Dlaczego dwie
osobne sesje”) — `upsert_valuation` robi własny `commit()` per portfel, co
mogłoby oddać połączenie do poola w trakcie trwania blokady, gdyby użyć tej
samej sesji do trzymania blokady i do właściwej pracy.

**Świadomie bez wpisu w `ingestion_runs`**: ta tabela jest o ingestii
cen/kursów per rynek (`market_code` to kolumna `NOT NULL`, FK do
`markets.code`, patrz `app/modules/marketdata/models.py`) — snapshot
portfeli nie ma rynku, sklejanie sztucznej wartości (np. `"PORTFOLIO"`) do
tej kolumny byłoby złamaniem jej sensu, nie odpowiednim rozszerzeniem.
Structured logi (`structlog`) są tu jedynym śladem przebiegu — wystarczające
dla tej warstwy (SKILL `job-eod` nie wymaga osobnej tabeli-logu per typ
joba, tylko dla ingestii cen).
"""

from __future__ import annotations

from datetime import date

import structlog

from app.db.advisory_lock import advisory_lock
from app.db.session import OwnerSessionLocal
from app.modules.portfolio import repository
from app.modules.portfolio import service as portfolio_service

logger = structlog.get_logger(__name__)


async def snapshot_portfolios(run_date: date | None = None) -> None:
    """Wycenia każdy portfel w systemie na `run_date` (domyślnie „dziś”,
    `portfolio_service.today()`) i zapisuje snapshot `portfolio_valuations`.

    Blokada doradcza Postgresa (`advisory_lock`, klucz
    `snapshot:{run_date}`) chroni przed dwoma równoległymi przebiegami dla
    tego samego dnia — jeśli inny proces już ją trzyma, ten przebieg po
    prostu kończy się bez pracy (inny i tak liczy to samo, idempotentnie).

    Błąd wyceny pojedynczego portfela (np. zepsute dane pozycji) nie
    przerywa reszty (SKILL `job-eod` reguła 6, ten sam wzorzec co
    `_ingest_asset_ohlcv` w `ingest_market.py`) — logowany z `portfolio_id`
    i błędem, pomijany, reszta portfeli liczy się dalej.
    """
    effective_date = run_date or portfolio_service.today()
    lock_key = f"snapshot:{effective_date.isoformat()}"

    logger.info("snapshot_portfolios.starting", run_date=effective_date.isoformat())

    async with OwnerSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key=lock_key) as acquired:
            if not acquired:
                logger.info(
                    "snapshot_portfolios.lock_not_acquired",
                    run_date=effective_date.isoformat(),
                )
                return

            async with OwnerSessionLocal() as db:
                portfolios = await repository.list_all_portfolios(db)

                ok_count = 0
                failed_count = 0
                for portfolio in portfolios:
                    try:
                        value = await portfolio_service.current_value(db, portfolio, effective_date)
                        composition_change = portfolio.holdings_changed_at == effective_date
                        await repository.upsert_valuation(
                            db,
                            portfolio_id=portfolio.id,
                            date=effective_date,
                            value_pln=value.total_pln,
                            composition_change=composition_change,
                        )
                    except Exception as exc:
                        failed_count += 1
                        logger.error(
                            "snapshot_portfolios.portfolio_failed",
                            portfolio_id=str(portfolio.id),
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        continue
                    ok_count += 1

                logger.info(
                    "snapshot_portfolios.done",
                    run_date=effective_date.isoformat(),
                    portfolios_total=len(portfolios),
                    ok=ok_count,
                    failed=failed_count,
                )


__all__ = ["snapshot_portfolios"]
