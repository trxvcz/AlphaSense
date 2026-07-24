"""Blokada doradcza Postgresa (`pg_advisory_lock`) — używana przez joby EOD
workera (plan krok 23, etap 4, SKILL `job-eod`, reguła 3), żeby dwa
uruchomienia tego samego joba (np. worker + ręczny `python -m app.cli
ingest` w tym samym momencie, albo dwie repliki workera w przyszłości) nie
próbowały ingestii tego samego rynku/dnia równolegle.

Umieszczone w `app/db/` (obok `session.py`/`base.py`), nie w `worker/` — to
generyczna infrastruktura Postgresa, niezwiązana z konkretnym modułem
domenowym ani z workerem: przyda się wszędzie tam, gdzie trzeba
zserializować pracę między procesami bez własnej tabeli-blokady (np.
przyszły job `snapshot_portfolios`, etap 5, patrz `worker/jobs/
snapshot_portfolios.py`), a `app/cli.py` też z niej korzysta pośrednio
(wywołuje `ingest_market` bezpośrednio, bez schedulera).

**Ważne dla wołających:** blokada jest *sesyjna* (`pg_try_advisory_lock`/
`pg_advisory_unlock`, nie warianty `_xact_`), czyli przywiązana do jednego
fizycznego połączenia z Postgresem, a nie do transakcji. `advisory_lock`
gwarantuje, że wzięcie i zwolnienie wykonają się na tym samym połączeniu
(nie robi `commit()`/`rollback()` na `db` w środku), ale jeśli wołający sam
zrobi `commit()`/`rollback()` na `db` *wewnątrz* bloku `async with`,
SQLAlchemy może odesłać połączenie do poola i przy następnym zapytaniu wziąć
inne — blokada zostałaby wtedy zwolniona niejawnie (fizyczne połączenie w
puli nadal ją trzyma, dopóki nie zostanie zamknięte, ale już nie na sesji
wołającego) bez naszej wiedzy. Dlatego `worker/jobs/ingest_market.py` trzyma
blokadę na **osobnej, dedykowanej sesji**, która w środku bloku nie robi nic
poza `yield` — cała właściwa praca (zapytania, commity przez `upsert_*`)
idzie przez inną, oddzielną sesję.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# `pg_try_advisory_lock(bigint)` przyjmuje 64-bit signed integer. Bierzemy
# pierwsze 8 bajtów SHA-256 klucza tekstowego i maskujemy najstarszy bit,
# żeby zawsze dostać nieujemną liczbę w zakresie 63 bitów — Postgres
# równie dobrze przyjąłby wartości ujemne, ale dodatnie są czytelniejsze
# przy diagnozie (`SELECT * FROM pg_locks WHERE locktype = 'advisory'`) i
# nie trzeba się zastanawiać nad reprezentacją znaku przy konwersji z
# nieoznaczonego hasha.
_SIGN_MASK = 0x7FFFFFFFFFFFFFFF


def _lock_key(key: str) -> int:
    """Hashuje `key` (dowolny string, np. `f"eod:{market_code}:{run_date}"`)
    na 63-bitową nieujemną liczbę całkowitą do `pg_try_advisory_lock`."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & _SIGN_MASK


@asynccontextmanager
async def advisory_lock(db: AsyncSession, *, key: str) -> AsyncGenerator[bool, None]:
    """Próbuje wziąć blokadę doradczą Postgresa dla `key`.

    **Nieblokujące** (`pg_try_advisory_lock`, nie `pg_advisory_lock`) — jeśli
    inny proces już trzyma blokadę dla tego `key`, `acquired` w `async with
    advisory_lock(...) as acquired` jest od razu `False`; wołający **nie**
    czeka w nieskończoność, decyduje sam, co zrobić (SKILL `job-eod`: „job
    już działa gdzie indziej, pomijam").

    Zawsze zwalnia blokadę w `finally`, jeśli została wzięta — nawet gdy kod
    w bloku `async with` rzuci wyjątek.
    """
    numeric_key = _lock_key(key)
    result = await db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": numeric_key})
    acquired = bool(result.scalar_one())
    if not acquired:
        logger.info("advisory_lock.not_acquired", key=key, numeric_key=numeric_key)
    try:
        yield acquired
    finally:
        if acquired:
            await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": numeric_key})
            logger.debug("advisory_lock.released", key=key, numeric_key=numeric_key)


__all__ = ["advisory_lock"]
