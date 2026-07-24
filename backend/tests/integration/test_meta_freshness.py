"""Testy `GET /meta/freshness` — plan krok 24, etap 4.

Integracyjne (prawdziwa baza). `markets` jest słownikiem seedowanym raz
(`make seed`, ADR-102) — ten plik nie tworzy własnych rynków (kolizja z FK
`assets.market_code`/`ingestion_runs.market_code` nie jest tego warta), tylko
dopisuje/usuwa własne `ingestion_runs` dla dwóch rynków, które i tak są
w słowniku (`GPW`, `US`), i sprząta po każdym teście — nie zakłada nic o
zawartości `ingestion_runs` poza tym, co sam wstawił.

Endpoint jest publiczny (bez `Authorization`) — patrz docstring
`app/modules/marketdata/routes.py`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import IngestionRun

_TEST_MARKET_CODES = ("GPW", "US")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_ingestion_runs(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    yield
    await db_session.execute(
        delete(IngestionRun).where(IngestionRun.market_code.in_(_TEST_MARKET_CODES))
    )
    await db_session.commit()


async def test_freshness_returns_200_and_lists_all_markets_even_without_runs(
    client: AsyncClient,
) -> None:
    """Zero `ingestion_runs` dla danego rynku (np. świeży env, worker jeszcze
    nie uruchomiony) to `stale=True`/`last_run_at=None`, nigdy 500.
    """
    resp = await client.get("/api/meta/freshness")

    assert resp.status_code == 200
    body = resp.json()
    codes = {market["code"] for market in body["markets"]}
    assert _TEST_MARKET_CODES[0] in codes  # GPW z seedu — zawsze w słowniku

    gpw = next(m for m in body["markets"] if m["code"] == "GPW")
    if gpw["last_run_at"] is None:
        assert gpw["stale"] is True
        assert gpw["status"] is None


async def test_freshness_marks_run_from_today_as_fresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        IngestionRun(
            market_code="GPW",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
            provider="stooq",
            assets_total=5,
            assets_ok=5,
            status="ok",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/meta/freshness")

    assert resp.status_code == 200
    gpw = next(m for m in resp.json()["markets"] if m["code"] == "GPW")
    assert gpw["stale"] is False
    assert gpw["status"] == "ok"
    assert gpw["last_run_at"] is not None


async def test_freshness_marks_old_run_as_stale(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        IngestionRun(
            market_code="US",
            started_at=now - timedelta(days=10),
            finished_at=now - timedelta(days=10) + timedelta(hours=1),
            provider="yfinance",
            assets_total=5,
            assets_ok=3,
            status="partial",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/meta/freshness")

    assert resp.status_code == 200
    us = next(m for m in resp.json()["markets"] if m["code"] == "US")
    assert us["stale"] is True
    assert us["status"] == "partial"


async def test_freshness_uses_latest_run_when_market_has_several(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            IngestionRun(
                market_code="GPW",
                started_at=now - timedelta(days=20),
                finished_at=now - timedelta(days=20) + timedelta(hours=1),
                provider="stooq",
                assets_total=5,
                assets_ok=5,
                status="ok",
            ),
            IngestionRun(
                market_code="GPW",
                started_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=2),
                provider="stooq",
                assets_total=5,
                assets_ok=4,
                status="partial",
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/meta/freshness")

    assert resp.status_code == 200
    gpw = next(m for m in resp.json()["markets"] if m["code"] == "GPW")
    assert gpw["status"] == "partial"  # najnowszy przebieg, nie najstarszy
    assert gpw["stale"] is False
