"""Entrypoint APScheduler workera (plan krok 23, etap 4).

Osobny proces/kontener od API (ten sam obraz Dockera, inny `command:` w
`docker-compose.yml` — dodawane w kolejnym podkroku, poza zakresem tego
pliku). Harmonogram czyta `markets` (kod, `timezone`, `eod_time`) **przy
starcie** — dodanie rynku to wiersz w tabeli, nie zmiana kodu (CLAUDE.md
#3.6, SKILL `job-eod`, reguła 2). Jeden `CronTrigger` per rynek, w strefie
czasowej *tego rynku* (nie serwera) — `AsyncIOScheduler`/APScheduler liczy
wtedy sam moment odpalenia poprawnie względem czasu letniego/zimowego danej
strefy, worker nie musi nic przeliczać.

Rejestracja jest jednorazowa, przy starcie procesu — worker nie dogląda
zmian w `markets` w locie (dopisanie/zmiana rynku wymaga restartu workera,
tak jak każdej zmiany konfiguracji czytanej raz przy starcie w tym
projekcie, np. `Settings`). Wystarczające dla skali tego projektu
(kilkanaście rynków, zmieniane rzadko, ręcznie).
"""

from __future__ import annotations

import asyncio
import signal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.modules.marketdata.models import Market
from worker.jobs.ingest_market import ingest_market

logger = structlog.get_logger(__name__)

# Margines na uruchomienie spóźnionego joba (np. worker był akurat
# restartowany dokładnie o `eod_time`) zamiast po cichu go pomijać —
# godzina wystarcza przy jobach dobowych (SKILL `job-eod`: kolejne
# przebiegi tego samego dnia i tak są idempotentne, `ON CONFLICT DO
# UPDATE`, więc spóźnione odpalenie nie szkodzi).
_MISFIRE_GRACE_SECONDS = 3600


async def _load_markets() -> list[Market]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Market).order_by(Market.code))
        return list(result.scalars().all())


def _register_jobs(scheduler: AsyncIOScheduler, markets: list[Market]) -> None:
    for market in markets:
        trigger = CronTrigger(
            hour=market.eod_time.hour,
            minute=market.eod_time.minute,
            timezone=market.timezone,
        )
        scheduler.add_job(
            ingest_market,
            trigger=trigger,
            kwargs={"market_code": market.code},
            id=f"eod:{market.code}",
            name=f"ingest_market[{market.code}]",
            replace_existing=True,
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
            # `ingest_market` bierze własną blokadę doradczą Postgresa
            # (`app/db/advisory_lock.py`) — `coalesce`/nie-współbieżność
            # per-job APScheduler i tak by wystarczyły w jednym procesie,
            # ale blokada w bazie jest tym, co faktycznie chroni przed
            # kolizją między workerem a ręcznym `python -m app.cli ingest`
            # albo (w przyszłości) drugą repliką workera.
        )
        logger.info(
            "scheduler.job_registered",
            market_code=market.code,
            timezone=market.timezone,
            eod_time=market.eod_time.isoformat(),
        )


async def main() -> None:
    markets = await _load_markets()
    if not markets:
        logger.warning("scheduler.no_markets_found")

    scheduler = AsyncIOScheduler()
    _register_jobs(scheduler, markets)
    scheduler.start()
    logger.info("scheduler.started", jobs=len(markets))

    stop_event = asyncio.Event()

    def _handle_stop(*_args: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_stop)

    await stop_event.wait()
    scheduler.shutdown(wait=True)
    logger.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())
