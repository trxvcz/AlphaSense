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

from httpx import AsyncClient

from app.core.config import get_settings

_AUTH_LIMIT = get_settings().rate_limit_auth_per_minute
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
