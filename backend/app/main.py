"""Punkt wejścia aplikacji FastAPI.

Rejestruje routery modułów pod prefiksem `/api`, mapuje wyjątki domenowe
(`app.core.errors.DomainError`) na odpowiedzi HTTP w formacie kontraktu API
(`docs/api-kontrakt.md`, sekcja „Błędy") i konfiguruje CORS oraz rate
limiting (`slowapi`, etap 2 krok 16). Sam nie zawiera logiki domenowej.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.rate_limit import limiter
from app.modules.analytics.routes import router as analytics_router
from app.modules.auth.routes import router as auth_router
from app.modules.marketdata.routes import router as marketdata_router
from app.modules.news.routes import router as news_router
from app.modules.portfolio.routes import router as portfolio_router

settings = get_settings()

app = FastAPI(title="AlphaSense API", debug=settings.env == "dev")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (slowapi, krok 16) — limiter oparty na Redisie, patrz
# `core/rate_limit.py`. Limit domyślny stosuje `SlowAPIMiddleware` do
# każdej trasy; limity ostrzejsze (np. `/auth/register`, `/auth/login`)
# nakłada dekorator `@limiter.limit(...)` w routerach modułów.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(marketdata_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(news_router, prefix="/api")


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
