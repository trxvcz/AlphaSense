"""Testy rate limitingu (`slowapi`, plan krok 16, etap 2).

Limit ostrzejszy na `/auth/register` i `/auth/login`
(`Settings.rate_limit_auth_per_minute`, `AUTH_RATE_LIMIT` w
`core/rate_limit.py`) liczony w Redisie — nie w pamięci procesu, patrz
`core/rate_limit.py`. Redis jest już częścią stacku testowego (ten sam,
z którego korzysta `core/cache.py` w dev/CI — `REDIS_URL`), więc te testy
nie są „network" (zero wywołań do sieci zewnętrznej), tylko integracyjne
z rzeczywistym Redisem, tak jak inne testy modułu `auth` są integracyjne
z rzeczywistym Postgresem.

Fixture `_reset_rate_limiter` (`conftest.py`) czyści liczniki `slowapi`
przed każdym testem — bez tego liczby żądań poniżej zależałyby od tego,
ile innych żądań do `/auth/register`/`/auth/login` wykonały wcześniejsze
testy w tej samej sesji pytest (ASGITransport nie ustawia `request.client`,
więc `get_remote_address` zwraca ten sam adres dla każdego żądania testowego
— wszystkie żądania w sesji dzielą jeden licznik per trasa bez resetu).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import cache as cache_module
from app.core.config import get_settings

_AUTH_LIMIT = get_settings().rate_limit_auth_per_minute
_DEFAULT_LIMIT = get_settings().rate_limit_default_per_minute
# Ile żądań PONAD limit wysyłamy, żeby zobaczyć 429 — kilka, nie jedno, bo
# okno stałe (`DefaultRateLimitMiddleware`) mogłoby się przewinąć dokładnie
# na styku i pojedyncze nadmiarowe żądanie trafiłoby już w nowe okno.
_OVER_LIMIT_MARGIN = 3
_WRONG_LOGIN = {"email": "nikt-taki-nie-istnieje@example.com", "password": "whatever-12345"}


def _register_payload(i: int) -> dict[str, str]:
    return {"email": f"limit-test-{i}@example.com", "password": "correct-password-1"}


async def test_requests_within_auth_limit_are_not_blocked(client: AsyncClient) -> None:
    """`_AUTH_LIMIT` żądań do `/auth/register` w oknie — żadne nie jest 429."""
    for i in range(_AUTH_LIMIT):
        resp = await client.post("/api/auth/register", json=_register_payload(i))
        assert resp.status_code == 201, resp.json()


async def test_login_over_auth_limit_returns_429_with_contract_error_shape(
    client: AsyncClient,
) -> None:
    """`_AUTH_LIMIT + 1` żądań do `/auth/login` — ostatnie przekracza limit.

    Nieudane logowanie (401, bo użytkownik nie istnieje) liczy się do limitu
    tak samo jak udane — decorator slowapi sprawdza limit przed wywołaniem
    handlera, niezależnie od wyniku biznesowego.
    """
    responses = [
        await client.post("/api/auth/login", json=_WRONG_LOGIN) for _ in range(_AUTH_LIMIT + 1)
    ]

    assert [r.status_code for r in responses[:_AUTH_LIMIT]] == [401] * _AUTH_LIMIT

    blocked = responses[_AUTH_LIMIT]
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"]["code"] == "rate_limited"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["error"]["details"] is not None


async def test_register_over_auth_limit_returns_429_with_contract_error_shape(
    client: AsyncClient,
) -> None:
    """To samo co powyżej, ale dla `/auth/register` (żeby złapać limit per-trasa,
    a nie tylko na jednym z dwóch ostrzej limitowanych endpointów).
    """
    for i in range(_AUTH_LIMIT):
        resp = await client.post("/api/auth/register", json=_register_payload(i))
        assert resp.status_code == 201

    blocked = await client.post("/api/auth/register", json=_register_payload(_AUTH_LIMIT))
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_auth_limit_on_one_route_does_not_block_the_other(client: AsyncClient) -> None:
    """Limit jest liczony per (adres, ścieżka) — wyczerpanie `/register` nie
    blokuje `/login` z tego samego „adresu" (docs/api-kontrakt.md: 429 jest
    właściwością konkretnej trasy, nie globalną blokadą klienta).
    """
    for i in range(_AUTH_LIMIT + 1):
        await client.post("/api/auth/register", json=_register_payload(i))

    still_blocked = await client.post("/api/auth/register", json=_register_payload(_AUTH_LIMIT + 1))
    assert still_blocked.status_code == 429

    login_resp = await client.post("/api/auth/login", json=_WRONG_LOGIN)
    assert login_resp.status_code == 401


# ---------------------------------------------------------------------------
# Limit domyślny (`DefaultRateLimitMiddleware`, naprawiony 2026-07-29)
# ---------------------------------------------------------------------------


async def test_default_limit_blocks_flood_on_ordinary_route(client: AsyncClient) -> None:
    """Zwykła trasa pod `/api` przestaje odpowiadać `200` po przekroczeniu
    `RATE_LIMIT_DEFAULT_PER_MINUTE`.

    Regresja na defekt znaleziony 2026-07-29: limit domyślny był zarejestrowany
    (`Limiter(default_limits=...)` + `SlowAPIMiddleware`) i **nie działał na
    żadnej trasie**, bo FastAPI 0.139 nie wystawia już `APIRoute` w
    `app.routes`, a slowapi traktuje nieznalezioną trasę jako zwolnioną z
    limitu. Kontrakt API deklarował ochronę, której nie było, i żaden test
    tego nie łapał — bo cała suita sprawdzała wyłącznie limity `/auth/*`,
    nakładane innym mechanizmem (dekoratorem).

    Trasa testowa to publiczne `GET /meta/freshness` — bez logowania, więc
    test nie zużywa slotów ostrzejszego limitu `/auth/*`.
    """
    responses = [
        await client.get("/api/meta/freshness") for _ in range(_DEFAULT_LIMIT + _OVER_LIMIT_MARGIN)
    ]
    codes = [r.status_code for r in responses]

    assert codes[:_DEFAULT_LIMIT] == [200] * _DEFAULT_LIMIT
    assert set(codes[_DEFAULT_LIMIT:]) == {429}

    body = responses[-1].json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["details"]["limit"] == f"{_DEFAULT_LIMIT} per 1 minute"


class _BrokenRedis:
    """Redis odmawiający połączenia na operacjach limitu domyślnego."""

    async def incr(self, key: str) -> int:
        raise RedisConnectionError("connection refused (test)")

    async def expire(self, key: str, seconds: int) -> bool:
        raise RedisConnectionError("connection refused (test)")


async def test_default_limit_lets_traffic_through_when_redis_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Padnięty Redis nie może zamienić limitu domyślnego w awarię API.

    Świadoma asymetria wobec limitu `/auth/*`, który przy padniętym Redisie
    zwraca błąd (przepuszczenie otwierałoby drogę do zgadywania haseł).
    Tutaj odwrotnie: zablokowanie wszystkiego zamieniłoby awarię CACHE'a w
    awarię CAŁEJ aplikacji, wbrew CLAUDE.md #3.7. Zapisane też w
    `docs/api-kontrakt.md`, sekcja „Rate limiting".
    """
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    resp = await client.get("/api/meta/freshness")

    assert resp.status_code == 200


async def test_health_is_exempt_from_default_limit(client: AsyncClient) -> None:
    """`GET /api/health` (krok 37) nie łapie `429` nawet daleko ponad limitem.

    Healthcheck kontenera odpytuje tę trasę co kilkanaście sekund z jednego
    adresu IP. Gdyby dzieliła licznik z monitoringiem zewnętrznym, Docker
    dostałby `429`, uznał zdrowy kontener API za padnięty i zrestartował go —
    czyli mechanizm chroniący przed zalewaniem API sam wywołałby awarię.

    Zwolnienie realizuje `DEFAULT_LIMIT_EXEMPT_PATHS`, nie `@limiter.exempt`:
    limit domyślny nakłada `DefaultRateLimitMiddleware`, którego dekorator
    slowapi w ogóle nie dotyczy.
    """
    codes = {
        (await client.get("/api/health")).status_code
        for _ in range(_DEFAULT_LIMIT + _OVER_LIMIT_MARGIN)
    }

    assert codes == {200}


async def test_default_limit_is_per_path(client: AsyncClient) -> None:
    """Wyczerpanie limitu na jednej trasie nie blokuje innej — licznik jest
    per (adres, ścieżka), tak jak deklaruje `docs/api-kontrakt.md`."""
    for _ in range(_DEFAULT_LIMIT + 1):
        await client.get("/api/meta/freshness")

    assert (await client.get("/api/meta/freshness")).status_code == 429
    assert (await client.get("/api/assets/search", params={"q": "nic"})).status_code == 200
