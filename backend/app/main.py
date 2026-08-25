"""Punkt wejścia aplikacji FastAPI.

Rejestruje routery modułów pod prefiksem `/api`, mapuje wyjątki domenowe
(`app.core.errors.DomainError`) na odpowiedzi HTTP w formacie kontraktu API
(`docs/api-kontrakt.md`, sekcja „Błędy") i konfiguruje CORS, rate limiting
(etap 2 krok 16) oraz Sentry (etap 7 krok 37). Sam nie zawiera logiki
domenowej.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.health import router as health_router
from app.core.observability import init_sentry
from app.core.rate_limit import DefaultRateLimitMiddleware, limiter
from app.modules.analytics.routes import router as analytics_router
from app.modules.auth.routes import router as auth_router
from app.modules.dividends.routes import router as dividends_router
from app.modules.marketdata.routes import router as marketdata_router
from app.modules.news.routes import router as news_router
from app.modules.portfolio.routes import router as portfolio_router
from app.modules.tags.routes import router as tags_router
from app.modules.watchlist.routes import router as watchlist_router

settings = get_settings()

# Sentry (krok 37) PRZED utworzeniem `FastAPI` — integracja Starlette/FastAPI
# opakowuje aplikację w momencie jej budowy, więc odwrotna kolejność zostawiłaby
# nieobsłużone wyjątki żądań poza raportowaniem. Bez `SENTRY_DSN` (dev, testy)
# to no-op, patrz `core/observability.py`.
init_sentry("api")

app = FastAPI(title="AlphaSense API", debug=settings.env == "dev")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (krok 16, limit domyślny poprawiony 2026-07-29) — liczniki
# w Redisie, patrz
# `core/rate_limit.py`. Dwie warstwy, celowo różnymi mechanizmami:
#  - limit DOMYŚLNY na każdej trasie: `DefaultRateLimitMiddleware` (własne,
#    kilkanaście linii na `INCR`/`EXPIRE`). `SlowAPIMiddleware` było tu
#    wcześniej i nie działało ani na jednej trasie — powód i dowód w
#    docstringu `DefaultRateLimitMiddleware`;
#  - limity OSTRZEJSZE (`/auth/register`, `/auth/login`): dekorator
#    `@limiter.limit(...)` w routerze modułu. Ten mechanizm działał i działa
#    (sprawdza limit wewnątrz endpointu, bez szukania trasy).
# `app.state.limiter` jest wymagane przez slowapi dla ścieżki dekoratora.
app.state.limiter = limiter
app.add_middleware(DefaultRateLimitMiddleware)

# `/api/health` (krok 37) mieszka w `core/`, nie w module domenowym: nie dotyka
# żadnego zasobu użytkownika i nie ma warstw routes → service → repository.
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(marketdata_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(news_router, prefix="/api")
app.include_router(dividends_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Jedyne miejsce mapowania wyjątków domenowych na HTTP (docs/api-kontrakt.md)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Mapuje `RateLimitExceeded` (slowapi) na format błędów kontraktu API.

    `slowapi` rzuca wyjątek z własnej klasy (nie `DomainError`) — mapowanie
    żyje tu, osobno od `domain_error_handler`, ale zgodnie z tą samą zasadą
    „jedno miejsce na mapowanie na HTTP" (docs/api-kontrakt.md, sekcja
    „Błędy", 429).
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": "Przekroczono limit żądań, spróbuj ponownie później.",
                "details": {"limit": str(exc.detail)},
            }
        },
    )
