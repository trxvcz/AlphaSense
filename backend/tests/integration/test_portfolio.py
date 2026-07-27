"""Testy `/portfolios` — CRUD portfeli (plan krok 25, etap 5).

Integracyjne, prawdziwa baza (`_clean_auth_tables` w `conftest.py` czyści
`users` CASCADE przed każdym testem — kaskadowo usuwa też `portfolios`/
`holdings` poprzedniego przebiegu, patrz STATUS.md). Testy 404 dla cudzego
zasobu tutaj uzupełniają (nie zastępują) parametryzowany
`tests/test_isolation.py`, który sprawdza to samo automatycznie dla
wszystkich tras naraz.
"""

from __future__ import annotations

from httpx import AsyncClient

EMAIL_A = "portfolio-a@example.com"
EMAIL_B = "portfolio-b@example.com"
PASSWORD = "correct-password-1"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_portfolio_happy_path(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)

    resp = await client.post(
        "/api/portfolios", json={"name": "Mój portfel", "type": "standard"}, headers=_auth(token)
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Mój portfel"
    assert body["type"] == "standard"
    assert body["holdings_version"] == 0
    assert "id" in body
    assert "created_at" in body


async def test_create_portfolio_rejects_empty_name(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)

    resp = await client.post(
        "/api/portfolios", json={"name": "", "type": "standard"}, headers=_auth(token)
    )

    assert resp.status_code == 422


async def test_list_portfolios_only_returns_own(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)

    create_resp = await client.post(
        "/api/portfolios", json={"name": "A", "type": "standard"}, headers=_auth(token_a)
    )
    assert create_resp.status_code == 201

    resp_a = await client.get("/api/portfolios", headers=_auth(token_a))
    assert resp_a.status_code == 200
    assert len(resp_a.json()) == 1

    resp_b = await client.get("/api/portfolios", headers=_auth(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []


async def test_get_update_delete_portfolio_happy_path(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    create_resp = await client.post(
        "/api/portfolios", json={"name": "Start", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Start"

    patch_resp = await client.patch(
        f"/api/portfolios/{portfolio_id}", json={"name": "Zmieniony"}, headers=_auth(token)
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Zmieniony"
    assert patch_resp.json()["type"] == "standard"  # pole nietknięte w PATCH zostaje

    delete_resp = await client.delete(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    get_after_delete = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    assert get_after_delete.status_code == 404


async def test_patch_portfolio_explicit_null_name_is_422(client: AsyncClient) -> None:
    """`name`/`type` to kolumny `NOT NULL` — jawny `null` w PATCH jest
    błędem klienta (422), nie cichym pominięciem (code-review etapu 5:
    inaczej żądanie zwracałoby 200 mimo zignorowanej wartości)."""
    token = await _register_and_login(client, EMAIL_A)
    create_resp = await client.post(
        "/api/portfolios", json={"name": "Start", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/portfolios/{portfolio_id}", json={"name": None}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_get_portfolio_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    create_resp = await client.post(
        "/api/portfolios", json={"name": "A", "type": "standard"}, headers=_auth(token_a)
    )
    portfolio_id = create_resp.json()["id"]

    resp = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_patch_portfolio_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    create_resp = await client.post(
        "/api/portfolios", json={"name": "A", "type": "standard"}, headers=_auth(token_a)
    )
    portfolio_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/portfolios/{portfolio_id}", json={"name": "Hack"}, headers=_auth(token_b)
    )

    assert resp.status_code == 404


async def test_delete_portfolio_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    create_resp = await client.post(
        "/api/portfolios", json={"name": "A", "type": "standard"}, headers=_auth(token_a)
    )
    portfolio_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/portfolios/{portfolio_id}", headers=_auth(token_b))

    assert resp.status_code == 404

    # portfel A nadal istnieje — żądanie B nie tylko odmówiło, ale nic nie usunęło
    still_there = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token_a))
    assert still_there.status_code == 200
