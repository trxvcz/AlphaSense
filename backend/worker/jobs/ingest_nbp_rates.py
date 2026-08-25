"""Job pobierania historii stopy referencyjnej NBP (plan krok 41a, etap 8).

Wzorzec ze skilla `job-eod`: blokada doradcza Postgresa, zapis idempotentny,
brak danych to nie awaria.

**Tygodniowy, nie dobowy i nie per rynek.** Stopę referencyjną zmienia RPP
kilka razy w roku, na posiedzeniach ogłaszanych z kalendarzem — dobowe
odpytywanie kupowałoby najwyżej kilkanaście godzin świeżości raz na kwartał.
ADR-102 (godziny EOD ze słownika `markets`) tego joba nie dotyczy: stopa
procentowa nie jest daną EOD żadnej giełdy i nie ma godziny zamknięcia.

**Jedno żądanie na przebieg, zawsze o pełną historię.** Archiwum NBP to
jeden plik z ~96 wierszami — pobranie „tylko nowych" wymagałoby i tak
ściągnięcia całości, więc nie ma czego optymalizować, a pełny zapis przy
okazji naprawia ewentualną korektę starszej wartości.

**Brak klucza API i brak dobowego limitu** — `static.nbp.pl` jest publiczny.
Bezpiecznik (`GuardedReferenceRates`) jest tu mimo to, bo chroni przed czym
innym niż limit: przed dobijaniem się do padniętego źródła w każdym
przebiegu i przy każdym ręcznym uruchomieniu.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog

from app.core.errors import ProviderUnavailableError
from app.db.advisory_lock import advisory_lock
from app.db.session import AsyncSessionLocal
from app.modules.marketdata import repository
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.nbp_rates import (
    GuardedReferenceRates,
    NbpReferenceRatesProvider,
)
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

# Nazwa źródła zapisywana w `nbp_reference_rates.source` — ta sama
# konwencja co `prices.source` i `dividend_events.source`.
REFERENCE_RATE_SOURCE = "nbp"

_REQUEST_TIMEOUT = 20.0
# Jedno żądanie na przebieg tygodniowy; limiter istnieje wyłącznie po to,
# żeby ręczne uruchomienia w pętli (debug) też nie waliły w `static.nbp.pl`.
_REQUESTS_PER_MINUTE = 6


async def ingest_nbp_rates() -> None:
    """Pobiera i zapisuje pełną historię stopy referencyjnej NBP."""
    async with AsyncSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key="ingest_nbp_rates") as acquired:
            if not acquired:
                logger.info("ingest_nbp_rates.lock_not_acquired")
                return
            await _run()


async def _run() -> None:
    fetched_at = datetime.now(UTC)

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        provider = GuardedReferenceRates(
            NbpReferenceRatesProvider(client),
            RateLimiter(REFERENCE_RATE_SOURCE, _REQUESTS_PER_MINUTE),
            CircuitBreaker(REFERENCE_RATE_SOURCE),
        )
        try:
            rates = await provider.get_reference_rates()
        except ProviderUnavailableError as exc:
            # Świadomie bez `raise`: poprzednie wartości zostają w bazie i
            # są nadal poprawne (stopa obowiązuje do następnej decyzji RPP),
            # więc nieudany przebieg nie psuje Sharpe'a — najwyżej opóźnia
            # zauważenie zmiany o tydzień. Ślad zostaje w logu i w Sentry.
            logger.warning("ingest_nbp_rates.provider_failed", error=str(exc))
            return

    async with AsyncSessionLocal() as db:
        stored = await repository.upsert_reference_rates(
            db,
            rates,
            source=REFERENCE_RATE_SOURCE,
            fetched_at=fetched_at,
        )
        latest = await repository.get_latest_reference_rate_date(db)

    logger.info(
        "ingest_nbp_rates.finished",
        stored=stored,
        latest=latest.isoformat() if latest else None,
    )
