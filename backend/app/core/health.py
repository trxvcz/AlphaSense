"""`GET /api/health` — liveness i readiness API (plan krok 37).

Trasa infrastrukturalna, nie domenowa: nie dotyka żadnego zasobu użytkownika
i nie ma warstw `routes → service → repository`, więc żyje w `core/`, a nie
w `modules/` (CLAUDE.md sekcja 6/8).

**Publiczna i wyłączona z limitu domyślnego** — przez wpis w
`DEFAULT_LIMIT_EXEMPT_PATHS` (`core/rate_limit.py`), nie przez `@limiter.exempt`:
limit domyślny nakłada `DefaultRateLimitMiddleware`, a nie slowapi, więc
dekorator slowapi nie miałby tu żadnego skutku (byłby adnotacją, która
wygląda na zabezpieczenie i nim nie jest). Healthcheck kontenera odpytuje tę
trasę co kilkanaście sekund z tego samego adresu IP — pod limitem domyślnym
(100/min per IP + ścieżka) dzieliłaby licznik z monitoringiem zewnętrznym i
orkiestratorem, a wtedy `429` wyglądałoby dla Dockera jak awaria API i
zaczęłoby restartować zdrowy kontener.

**Nie ujawnia szczegółów awarii.** Trasa jest publiczna, więc odpowiedź niesie
wyłącznie `"up"`/`"down"` na komponent. Komunikat wyjątku (host bazy, nazwa
użytkownika, wersja Postgresa) trafia do logów i do Sentry, nie do odpowiedzi.

**Zawsze HTTP 200**, także gdy zależność leży — status czyta się z pola
`status` w ciele. Kod inny niż 2xx zarezerwowany jest na sytuację „proces API
w ogóle nie odpowiada", a healthcheck Dockera i tak interpretuje ciało (patrz
`docker-compose.prod.yml`). Zwracanie `503` przy padniętym Redisie zabiłoby
kontener API, mimo że aplikacja bez Redisa działa dalej — wolniej, ale
poprawnie (CLAUDE.md #3.7).
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import get_settings
from app.db.session import DbSession

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["meta"])

ComponentStatus = Literal["up", "down"]


class HealthOut(BaseModel):
    """Kształt odpowiedzi `GET /api/health` (docs/api-kontrakt.md)."""

    status: Literal["ok", "degraded"]
    db: ComponentStatus
    redis: ComponentStatus
    version: str


async def _check_db(db: AsyncSession) -> ComponentStatus:
    """`SELECT 1` — sprawdza, czy połączenie z bazą naprawdę działa.

    Samo istnienie puli połączeń nie wystarcza: kontener API wstaje szybciej
    niż Postgres kończy odtwarzanie po restarcie VPS-a i przez ten czas
    wygląda na zdrowy, mimo że pierwsze żądanie użytkownika padnie.
    """
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error("health.db_down", error=f"{type(exc).__name__}: {exc}")
        return "down"
    return "up"


async def _check_redis() -> ComponentStatus:
    """`PING` do Redisa. `RedisError` łapiemy szeroko — dla healthchecku nie
    ma różnicy między odmową połączenia, timeoutem a błędem protokołu.

    Klient pobierany przez `cache.get_redis()` (przez moduł, nie zaimportowaną
    nazwę) — dzięki temu test podmieniający `cache.get_redis` na podwójnego
    realnie wpływa na tę funkcję, tak samo jak na resztę `core/cache.py`."""
    try:
        await cache.get_redis().ping()
    except (RedisError, OSError) as exc:
        logger.warning("health.redis_down", error=f"{type(exc).__name__}: {exc}")
        return "down"
    return "up"


@router.get("/health", response_model=HealthOut)
async def health(db: DbSession) -> HealthOut:
    """Stan API i jego zależności.

    `status` jest `"ok"` tylko wtedy, gdy **oba** komponenty odpowiadają.
    Padnięty Redis daje `"degraded"`, nie `"down"` — cache można w każdej
    chwili wyczyścić i aplikacja ma działać (CLAUDE.md #3.7); traktowanie tego
    jak awarii całości byłoby fałszywym alarmem. Padnięta baza to realna
    awaria, ale też ląduje w `"degraded"`, bo pole `db` niesie już tę
    informację, a healthcheck kontenera odróżnia oba przypadki po nim.
    """
    settings = get_settings()
    db_status = await _check_db(db)
    redis_status = await _check_redis()

    return HealthOut(
        status="ok" if db_status == "up" and redis_status == "up" else "degraded",
        db=db_status,
        redis=redis_status,
        version=settings.app_version,
    )
