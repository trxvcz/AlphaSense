"""Rate limiting (plan krok 16, limit domyślny naprawiony 2026-07-29).

Liczniki w Redisie.

**Dwie warstwy, dwa różne mechanizmy:**

1. Limit DOMYŚLNY (`Settings.rate_limit_default_per_minute`, per adres IP +
   ścieżka) — `DefaultRateLimitMiddleware` niżej, rejestrowane w `app.main`.
   Bezpiecznik przeciw zalewaniu API.
2. Limit OSTRZEJSZY (`AUTH_RATE_LIMIT`) na `/auth/register` i `/auth/login` —
   dekorator `@limiter.limit(AUTH_RATE_LIMIT)` w `modules/auth/routes.py`.
   To jedyne dwie trasy podatne na zgadywanie hasła i zalewanie rejestracjami.
   `/auth/refresh`, `/auth/logout` i `/auth/google/*` zostają na limicie
   domyślnym: `refresh`/`logout` wymagają już poprawnego refresh tokenu
   (nie da się nimi zgadywać hasła), a `/google/*` idzie przez Google
   (własny rate limiting po ich stronie) i nie przyjmuje hasła.

Dlaczego dwa mechanizmy zamiast jednego — patrz docstring
`DefaultRateLimitMiddleware` (`SlowAPIMiddleware` nie egzekwowało limitu
domyślnego na ŻADNEJ trasie od czasu zmiany routingu w FastAPI 0.139).

Liczniki obu warstw żyją w Redisie, nie w pamięci procesu: w pamięci nie
przetrwałyby restartu kontenera ani nie działałyby poprawnie z wieloma
replikami API, a Redis jest już częścią stacku (`core/cache.py`).

**Awaria Redisa jest obsługiwana INACZEJ w każdej z warstw** — świadomie:
limit `/auth/*` przy padniętym Redisie zwraca błąd (`swallow_errors` i
`in_memory_fallback` slowapi zostają wyłączone), bo przepuszczenie żądań
otwierałoby drogę do brute-force na hasła; limit domyślny przepuszcza ruch
z logiem `warning`, bo zablokowanie wszystkiego zamieniłoby awarię cache'a
w awarię całego API, wbrew CLAUDE.md #3.7.
"""

from __future__ import annotations

import time

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core import cache
from app.core.config import get_settings

logger = structlog.get_logger(__name__)

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.redis_url,
)

AUTH_RATE_LIMIT = f"{_settings.rate_limit_auth_per_minute}/minute"

# Trasy wyłączone z limitu domyślnego. Dziś jedna: `GET /api/health` (krok 37)
# jest odpytywana maszynowo — healthcheck kontenera co kilkanaście sekund z
# jednego adresu IP dzieliłby licznik z monitoringiem zewnętrznym, a `429`
# wyglądałoby dla Dockera jak awaria API i restartowałoby zdrowy kontener.
# Ścieżki są pełne (z prefiksem `/api`), bo middleware widzi `request.url.path`
# po zamontowaniu routera, nie ścieżkę z dekoratora.
DEFAULT_LIMIT_EXEMPT_PATHS: frozenset[str] = frozenset({"/api/health"})

# Limit obejmuje wyłącznie trasy pod `/api` — dokładnie to, co deklaruje
# `docs/api-kontrakt.md`. Poza tym prefiksem żyje w tej aplikacji tylko
# `/openapi.json` i `/docs`, a na produkcji nie są one w ogóle osiągalne:
# Caddy kieruje pod API tylko `/api/*`, całą resztę do frontendu
# (`infra/caddy/Caddyfile`). Nie ma więc czego chronić, a każde żądanie poza
# `/api` oszczędza jedno okrążenie do Redisa.
_API_PREFIX = "/api"

_WINDOW_SECONDS = 60


class DefaultRateLimitMiddleware(BaseHTTPMiddleware):
    """Limit domyślny (`RATE_LIMIT_DEFAULT_PER_MINUTE`) per adres IP + ścieżka.

    **Dlaczego nie `SlowAPIMiddleware`.** Do 2026-07-29 limit domyślny był
    zarejestrowany przez `Limiter(default_limits=...)` + `SlowAPIMiddleware`
    i **nie działał ani na jednej trasie** — 130 żądań na `/api/meta/freshness`
    w 0,3 s przechodziło bez jednego `429` i bez śladu w Redisie, mimo że
    kontrakt API deklarował limit „na każdej trasie pod `/api`".

    Przyczyna: `SlowAPIMiddleware` szuka funkcji obsługującej trasę przez
    `_find_route_handler(app.routes, scope)`, które bierze pod uwagę wyłącznie
    obiekty z atrybutem `endpoint`. FastAPI 0.139 nie spłaszcza już
    `include_router` do listy `APIRoute` w `app.routes` — wstawia tam jeden
    obiekt `_IncludedRouter` na router, BEZ `endpoint`. Handler nigdy się nie
    znajdował, a `_should_exempt` traktuje `handler is None` jako „zwolnione
    z limitu", więc middleware przepuszczało wszystko. Ciche i wyglądające na
    działające.

    Limity `@limiter.limit(...)` na `/auth/login` i `/auth/register` działały
    i działają dalej — dekorator sprawdza limit wewnątrz endpointu, bez
    szukania trasy. To one chronią przed zgadywaniem hasła; limit domyślny to
    grubszy bezpiecznik przeciw zalewaniu API.

    **Okno stałe, nie przesuwne.** Licznik to `INCR` + `EXPIRE` na kluczu z
    numerem minuty — kilkanaście linii na publicznym API Redisa zamiast
    zależności od wewnętrznych mechanizmów wykrywania tras w cudzej
    bibliotece. Przy 100/min różnica między oknem stałym a przesuwnym
    (dopuszczalny krótki skok na styku dwóch okien) nie ma znaczenia dla
    zabezpieczenia przeciwzalewowego. Limity `/auth/*` zostają na przesuwnym
    oknie slowapi, bo tam precyzja realnie chroni hasła.

    **Awaria Redisa przepuszcza ruch** (log `warning`, bez `429`). To
    świadoma różnica wobec limitu `/auth/*`, który przy padniętym Redisie
    zwraca błąd: tam przepuszczenie wszystkiego byłoby otwarciem drogi do
    brute-force, tutaj zablokowanie wszystkiego zamieniłoby awarię CACHE'a w
    awarię CAŁEGO API — wbrew CLAUDE.md #3.7 („Redis można w każdej chwili
    wyczyścić i aplikacja musi działać").
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith(_API_PREFIX) or path in DEFAULT_LIMIT_EXEMPT_PATHS:
            return await call_next(request)

        limit = _settings.rate_limit_default_per_minute
        window = int(time.time()) // _WINDOW_SECONDS
        key = f"ratelimit:default:{get_remote_address(request)}:{path}:{window}"

        try:
            # Przez moduł, nie zaimportowaną nazwę — dzięki temu test może
            # podmienić `cache.get_redis` na podwójnego.
            redis = cache.get_redis()
            count = await redis.incr(key)
            if count == 1:
                # TTL ustawiany raz, przy pierwszym żądaniu w oknie — klucz i
                # tak zniknie, więc kolejne `EXPIRE` byłyby zbędnym round-tripem.
                await redis.expire(key, _WINDOW_SECONDS)
        except (RedisError, OSError) as exc:
            logger.warning("rate_limit.storage_unavailable", error=f"{type(exc).__name__}: {exc}")
            return await call_next(request)

        if count > limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Przekroczono limit żądań, spróbuj ponownie później.",
                        "details": {"limit": f"{limit} per 1 minute"},
                    }
                },
            )

        return await call_next(request)
