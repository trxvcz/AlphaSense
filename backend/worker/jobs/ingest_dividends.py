"""Job pobierania kalendarza dywidend (plan krok 47, etap 9).

Wzorzec ze skilla `job-eod`: blokada doradcza Postgresa, zapis idempotentny,
jeden padnięty symbol nie przerywa przebiegu.

**Job dobowy, nie per rynek i nie co pół godziny.** Zapowiedź dywidendy
zmienia się rzadko (kilka razy do roku na spółkę), a odpytywanie częstsze
niż raz dziennie kupowałoby nieaktualność liczoną w godzinach za cenę
dobowego budżetu dostawcy. ADR-102 (godziny EOD ze słownika `markets`) tego
joba nie dotyczy — zdarzenie dywidendowe nie jest daną EOD i nie ma godziny
zamknięcia.

**Budżet zapytań jest tu ograniczeniem pierwszej klasy.** Darmowy plan Alpha
Vantage to 25 zapytań na dobę, dzielone z jobem sentymentu z kroku 46
(12 przebiegów/dobę), a dostawca dywidend nie ma trybu zbiorczego — jeden
symbol to jedno zapytanie. Stąd `_MAX_SYMBOLS_PER_RUN`: przebieg bierze
najwyżej tyle symboli, ile mieści się w zapasie, a przy większej liczbie
aktywów kolejne przebiegi obsłużą resztę (kolejność jest stabilna, więc
rotacja idzie po `provider_symbol`, nie losowo).

**Pytamy wyłącznie o aktywa, które ktokolwiek trzyma** (`repository.
list_provider_symbols` łączy z `holdings`). Dywidenda aktywa, którego nikt
nie ma, nie trafi na żaden ekran, a kosztuje tyle samo co realna pozycja.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.db.advisory_lock import advisory_lock
from app.db.session import AsyncSessionLocal
from app.modules.dividends import repository
from app.modules.dividends.providers.alphavantage_dividends import (
    AlphaVantageDividendsProvider,
)
from app.modules.dividends.providers.base import DividendAnnouncement
from app.modules.dividends.service import DIVIDEND_PROVIDER

logger = structlog.get_logger(__name__)

# Ile symboli maksymalnie w jednym przebiegu — patrz docstring modułu.
# Osiem zostawia zapas w dobowym limicie 25 na job sentymentu (12) i na
# ręczne uruchomienie, zamiast trafiać w limit co do sztuki.
_MAX_SYMBOLS_PER_RUN = 8
_REQUEST_TIMEOUT = 20.0


@dataclass
class _Counters:
    symbols: int = 0
    fetched: int = 0
    stored: int = 0
    updated: int = 0
    failed_symbols: int = 0


async def ingest_dividends() -> None:
    """Pobiera zapowiedzi dywidend dla trzymanych aktywów zagranicznych.

    Blokada doradcza na stałym kluczu (jak w `ingest_news`, nie na dacie
    jak przy snapshotach): kluczem jest sam job. Dwa równoległe przebiegi
    nie zdublowałyby danych (`ON CONFLICT DO UPDATE`), ale zdublowałyby
    zapytania u dostawcy, którego dobowy limit jest tu wąskim gardłem.
    """
    settings = get_settings()
    if not settings.alphavantage_api_key:
        logger.info("ingest_dividends.no_api_key")
        return

    async with AsyncSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key="ingest_dividends") as acquired:
            if not acquired:
                logger.info("ingest_dividends.lock_not_acquired")
                return
            await _run()


async def _run() -> None:
    counters = _Counters()
    fetched_at = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        symbols = await repository.list_provider_symbols(db, DIVIDEND_PROVIDER)
        if not symbols:
            # Nie jest to awaria: tak wygląda instalacja z portfelem
            # wyłącznie z GPW, czyli scenariusz opisany w planie kroku 47
            # jako znane ograniczenie pokrycia.
            logger.info("ingest_dividends.no_mapped_holdings", provider=DIVIDEND_PROVIDER)
            return

        selected = symbols[:_MAX_SYMBOLS_PER_RUN]
        counters.symbols = len(selected)
        if len(symbols) > len(selected):
            logger.info(
                "ingest_dividends.budget_capped",
                mapped=len(symbols),
                taken=len(selected),
                limit=_MAX_SYMBOLS_PER_RUN,
            )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            provider = AlphaVantageDividendsProvider(client)
            for asset_id, provider_symbol, currency in selected:
                await _ingest_symbol(
                    db,
                    provider,
                    asset_id=asset_id,
                    provider_symbol=provider_symbol,
                    currency=currency,
                    fetched_at=fetched_at,
                    counters=counters,
                )

    logger.info(
        "ingest_dividends.finished",
        symbols=counters.symbols,
        fetched=counters.fetched,
        stored=counters.stored,
        updated=counters.updated,
        failed_symbols=counters.failed_symbols,
    )


async def _ingest_symbol(
    db: AsyncSession,
    provider: AlphaVantageDividendsProvider,
    *,
    asset_id: UUID,
    provider_symbol: str,
    currency: str,
    fetched_at: datetime,
    counters: _Counters,
) -> None:
    """Jeden symbol, jedna transakcja. Błąd **nie przerywa przebiegu** (SKILL
    `job-eod`, reguła 6) — reszta symboli ma się zaciągnąć, a pojedyncza
    awaria zostaje w logu z symbolem, którego dotyczy.

    **Commit po każdym symbolu, nie raz na końcu przebiegu.** Przy jednym
    commicie końcowym awaria ósmego symbolu — albo błąd bazy przy zapisie —
    unieważniałaby sesję i kasowała dane siedmiu poprzednich, czyli spalony
    dobowy budżet dostawcy bez żadnego zapisu. `rollback()` w gałęzi błędu
    przywraca sesję do stanu używalnego dla następnego symbolu.

    Łapiemy szeroko (`Exception`), nie tylko `ProviderUnavailableError`:
    `get_with_backoff` wypuszcza `httpx.HTTPStatusError`/`httpx.TransportError`
    wprost, a parser dostawcy może rzucić czymkolwiek na nieoczekiwanym
    kształcie odpowiedzi. Job dobowy ma dowieźć resztę symboli, a nie
    przewrócić się na jednym.
    """
    try:
        announcements = await provider.get_dividends(provider_symbol)

        counters.fetched += len(announcements)
        for announcement in announcements:
            await _store(
                db,
                announcement,
                asset_id=asset_id,
                currency=currency,
                fetched_at=fetched_at,
                counters=counters,
            )
        await db.commit()
    except ProviderUnavailableError as exc:
        await db.rollback()
        counters.failed_symbols += 1
        logger.warning(
            "ingest_dividends.provider_failed",
            symbol=provider_symbol,
            error=str(exc),
        )
    except Exception:
        await db.rollback()
        counters.failed_symbols += 1
        logger.exception(
            "ingest_dividends.symbol_failed",
            symbol=provider_symbol,
        )


async def _store(
    db: AsyncSession,
    announcement: DividendAnnouncement,
    *,
    asset_id: UUID,
    currency: str,
    fetched_at: datetime,
    counters: _Counters,
) -> None:
    """Zapisuje jedno zdarzenie.

    **Zapisujemy także zdarzenia z przeszłości**, mimo że kalendarz pokazuje
    wyłącznie przyszłe. Dostawca oddaje pełną historię w jednej odpowiedzi,
    więc odrzucanie jej nie oszczędza ani zapytania, ani ruchu — a zapisana
    daje bazę do przyszłego widoku historii wypłat (Etap 21) bez ponownego
    palenia dobowego limitu. Filtrowanie po dacie należy do odczytu
    (`repository.list_upcoming_events`), a nie do ingestii.

    Waluta pochodzi z `assets.currency`, bo `DIVIDENDS` jej nie podaje
    (patrz `alphavantage_dividends._parse_entry`).
    """
    is_new = await repository.upsert_dividend_event(
        db,
        asset_id=asset_id,
        ex_date=announcement.ex_date,
        amount=announcement.amount,
        currency=currency,
        source=DIVIDEND_PROVIDER,
        fetched_at=fetched_at,
        record_date=announcement.record_date,
        pay_date=announcement.pay_date,
        declaration_date=announcement.declaration_date,
    )
    if is_new:
        counters.stored += 1
    else:
        counters.updated += 1
