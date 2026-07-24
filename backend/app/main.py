"""Punkt wejścia aplikacji FastAPI.

Rejestruje routery modułów pod prefiksem `/api` i mapuje wyjątki domenowe
(`app.core.errors.DomainError`) na odpowiedzi HTTP w formacie kontraktu API
(`docs/api-kontrakt.md`, sekcja „Błędy"). Sam nie zawiera logiki domenowej —
to czysty szkielet etapu 1.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import DomainError
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
