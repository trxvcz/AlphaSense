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
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.observability import init_sentry
from app.db.session import OwnerSessionLocal
from app.modules.marketdata.models import Market
from worker.jobs.ingest_dividends import ingest_dividends
from worker.jobs.ingest_market import ingest_market
from worker.jobs.ingest_nbp_rates import ingest_nbp_rates
from worker.jobs.ingest_news import ingest_news, ingest_news_sentiment

logger = structlog.get_logger(__name__)

# Margines na uruchomienie spóźnionego joba (np. worker był akurat
# restartowany dokładnie o `eod_time`) zamiast po cichu go pomijać —
# godzina wystarcza przy jobach dobowych (SKILL `job-eod`: kolejne
# przebiegi tego samego dnia i tak są idempotentne, `ON CONFLICT DO
# UPDATE`, więc spóźnione odpalenie nie szkodzi).
_MISFIRE_GRACE_SECONDS = 3600
# Co ile minut odpytujemy feedy RSS. 30 minut to kompromis między
# świeżością a ruchem do cudzych serwerów: feedy oddają przesuwające się
# okno kilkudziesięciu pozycji, więc przy tym interwale nic nie umyka,
# a dobowy ruch to ~48 żądań na feed.
_NEWS_INTERVAL_MINUTES = 30
# Sentyment z Alpha Vantage — 120 minut, czyli 12 przebiegów na dobę przy
# jednym zapytaniu zbiorczym każdy. Ta liczba wynika wprost z limitu
# darmowego planu (25 zapytań/dobę): zostawia zapas na restart workera
# i na ręczne uruchomienie joba, zamiast trafiać w limit co do sztuki.
_SENTIMENT_INTERVAL_MINUTES = 120
# Kalendarz dywidend (krok 47) — raz na dobę, o 5:15 UTC. Zapowiedź
# dywidendy zmienia się kilka razy do roku na spółkę, więc częstsze pytanie
# kupowałoby nieaktualność liczoną w godzinach za cenę dobowego budżetu
# Alpha Vantage (25 zapytań, dzielone z jobem sentymentu). Godzina wcześnie
# rano i minuta różna od pełnej — żeby ten job nie startował równo z jobem
# sentymentu i nie konkurował z nim o te same tokeny limitera.
_DIVIDENDS_HOUR_UTC = 5
_DIVIDENDS_MINUTE = 15
# Stopa referencyjna NBP (krok 41a) — raz w tygodniu, w środę o 6:20 UTC.
# RPP obraduje zwykle w środy i publikuje decyzję tego samego dnia po
# południu, więc środowy poranek łapie decyzję z poprzedniego posiedzenia
# na pewno, a nie w połowie publikacji. Częstsze pytanie nic nie wnosi:
# między posiedzeniami stopa jest z definicji stała.
_NBP_RATES_DAY_OF_WEEK = "wed"
_NBP_RATES_HOUR_UTC = 6
_NBP_RATES_MINUTE = 20


async def _load_markets() -> list[Market]:
    async with OwnerSessionLocal() as db:
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

    # Newsy (krok 46, etap 9) — joby cykliczne, nie per rynek.
    # Feed RSS nie ma godziny zamknięcia ani przypisania do rynku, więc
    # `markets`/ADR-102 go nie dotyczą (uzasadnienie w `jobs/ingest_news.py`).
    # Interwał, nie cron: publikacja idzie przez cały dzień, a stała godzina
    # oznaczałaby, że poranna depesza czeka do wieczora.
    scheduler.add_job(
        ingest_news,
        trigger=IntervalTrigger(minutes=_NEWS_INTERVAL_MINUTES),
        # `news:ingest`, nie `news:rss` — od dołożenia Finnhuba ten job
        # obsługuje dwa źródła, a `id` jest widoczne w logach i w panelu
        # diagnostycznym, więc nie może opisywać połowy zakresu.
        id="news:ingest",
        name="ingest_news",
        replace_existing=True,
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
    )
    logger.info(
        "scheduler.job_registered", job="ingest_news", interval_minutes=_NEWS_INTERVAL_MINUTES
    )

    # Sentyment (Alpha Vantage) chodzi RZADZIEJ i dlatego jest osobnym jobem:
    # darmowy plan to 25 zapytań na dobę, a `ingest_news` odpala się 48 razy.
    # Pełne uzasadnienie w docstringu `ingest_news_sentiment`.
    scheduler.add_job(
        ingest_news_sentiment,
        trigger=IntervalTrigger(minutes=_SENTIMENT_INTERVAL_MINUTES),
        id="news:sentiment",
        name="ingest_news_sentiment",
        replace_existing=True,
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
    )
    logger.info(
        "scheduler.job_registered",
        job="ingest_news_sentiment",
        interval_minutes=_SENTIMENT_INTERVAL_MINUTES,
    )

    # Dywidendy (krok 47, etap 9) — `CronTrigger`, nie `IntervalTrigger`:
    # interwał dobowy liczyłby się od startu workera, więc każdy restart
    # przesuwałby porę odpytywania dostawcy. Przy jobie, którego jedynym
    # realnym ograniczeniem jest dobowy limit zapytań, pora ma być
    # przewidywalna. Strefa UTC świadomie: to nie jest dana EOD żadnego
    # rynku, więc `markets`/ADR-102 nie mają tu czego rozstrzygać.
    scheduler.add_job(
        ingest_dividends,
        trigger=CronTrigger(hour=_DIVIDENDS_HOUR_UTC, minute=_DIVIDENDS_MINUTE, timezone="UTC"),
        id="dividends:ingest",
        name="ingest_dividends",
        replace_existing=True,
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
    )
    logger.info(
        "scheduler.job_registered",
        job="ingest_dividends",
        hour_utc=_DIVIDENDS_HOUR_UTC,
        minute=_DIVIDENDS_MINUTE,
    )

    # Stopa referencyjna NBP (krok 41a, etap 8) — wejście do Sharpe'a.
    # `CronTrigger` z tego samego powodu co przy dywidendach: interwał
    # tygodniowy liczony od startu workera dryfowałby po kalendarzu przy
    # każdym restarcie. UTC świadomie — to nie jest dana EOD żadnego rynku.
    scheduler.add_job(
        ingest_nbp_rates,
        trigger=CronTrigger(
            day_of_week=_NBP_RATES_DAY_OF_WEEK,
            hour=_NBP_RATES_HOUR_UTC,
            minute=_NBP_RATES_MINUTE,
            timezone="UTC",
        ),
        id="nbp:reference_rates",
        name="ingest_nbp_rates",
        replace_existing=True,
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
    )
    logger.info(
        "scheduler.job_registered",
        job="ingest_nbp_rates",
        day_of_week=_NBP_RATES_DAY_OF_WEEK,
        hour_utc=_NBP_RATES_HOUR_UTC,
        minute=_NBP_RATES_MINUTE,
    )


async def main() -> None:
    # Krok 37: bez DSN to no-op (dev). Padnięty job trafia do Sentry przez
    # `logging.exception` APSchedulera (`LoggingIntegration`), a `status`
    # `failed`/`partial` — jawnym `capture_message` w `ingest_market`.
    init_sentry("worker")

    markets = await _load_markets()
    if not markets:
        logger.warning("scheduler.no_markets_found")

    scheduler = AsyncIOScheduler()
    _register_jobs(scheduler, markets)
    scheduler.start()
    # Liczone z harmonogramu, nie z `len(markets)` — od kroku 46 jobów jest
    # więcej niż rynków (`ingest_news`, `ingest_news_sentiment`), a licznik,
    # który o tym nie wie, po cichu kłamie w logach startowych.
    logger.info("scheduler.started", jobs=len(scheduler.get_jobs()))

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
