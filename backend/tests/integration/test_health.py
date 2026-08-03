"""Testy `GET /api/health` — liveness i readiness API (plan krok 37).

Integracyjne, prawdziwa baza i prawdziwy Redis (jak `test_rate_limit.py`).
Przypadki awarii zależności są wstrzykiwane: podwójny Redisa rzucający
`ConnectionError` i podmieniona zależność `get_db` z sesją, która odmawia
wykonania zapytania — kładzenie realnych kontenerów w środku suity nie
wchodzi w grę.

Zwolnienie `/health` z limitu domyślnego testuje `test_rate_limit.py`
(`test_health_is_exempt_from_default_limit`) — tam, gdzie mieszka reszta
wiedzy o limitach.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.core import cache as cache_module
from app.db.session import get_db
from app.main import app


class _BrokenRedis:
    """Redis, który odmawia połączenia na każdą operację."""

    async def ping(self) -> bool:
        raise RedisConnectionError("connection refused (test)")


class _BrokenSession:
    """Sesja bazy, która przepuszcza `SELECT 1` w błąd — symuluje Postgresa
    niedostępnego w chwili odpytania (np. jeszcze odtwarzającego się po
    restarcie VPS-a)."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused (test)"))


async def test_health_happy_path_reports_all_components_up(client: AsyncClient) -> None:
    resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "up"
    assert body["redis"] == "up"
    assert isinstance(body["version"], str) and body["version"]


async def test_health_is_public(client: AsyncClient) -> None:
    """Bez nagłówka `Authorization` — healthcheck kontenera i monitoring
    zewnętrzny nie mają skąd wziąć tokenu."""
    resp = await client.get("/api/health", headers={})

    assert resp.status_code == 200


async def test_health_reports_degraded_when_redis_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Padnięty Redis to `degraded`, nie błąd HTTP.

    Zwrócenie `503` restartowałoby zdrowy kontener API przez healthcheck
    Dockera, mimo że aplikacja bez Redisa działa dalej — wolniej, ale
    poprawnie (CLAUDE.md #3.7).
    """
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "down"
    assert body["db"] == "up"


async def test_health_reports_degraded_when_db_is_down(client: AsyncClient) -> None:
    async def _broken_db() -> AsyncGenerator[_BrokenSession, None]:
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_db
    try:
        resp = await client.get("/api/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "down"


async def test_health_does_not_leak_failure_details(client: AsyncClient) -> None:
    """Trasa jest publiczna, więc odpowiedź niesie wyłącznie `up`/`down`.

    Komunikat wyjątku (host bazy, nazwa użytkownika, wersja serwera) ma
    trafiać do logów i do Sentry, nigdy do ciała odpowiedzi.
    """

    async def _broken_db() -> AsyncGenerator[_BrokenSession, None]:
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_db
    try:
        resp = await client.get("/api/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    raw = resp.text
    assert "connection refused" not in raw
    assert "OperationalError" not in raw
    assert set(resp.json()) == {"status", "db", "redis", "version"}
