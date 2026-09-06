"""Row Level Security — trzecia warstwa ADR-002 (plan krok 44).

Ten plik pilnuje czegoś, czego nie sprawdza `tests/test_isolation.py`:
tamten testuje **warstwę aplikacyjną** (`get_owned_*` zwraca 404 na cudzy
zasób), ten — że nawet zapytanie, które ominęłoby zależność autoryzacyjną,
nie zobaczy cudzych wierszy, bo nie przepuści ich baza.

**Najgroźniejszy scenariusz tego kroku to zielone testy przy wyłączonej
ochronie.** Superużytkownik i właściciel tabeli omijają polityki milcząco,
więc suita połączona jako `portfel` przechodziłaby cała, nie sprawdziwszy
niczego. Stąd `test_rola_aplikacji_nie_omija_polityk` — jeśli kiedyś
`DATABASE_URL_APP` zniknie z konfiguracji albo rola dostanie `BYPASSRLS`,
ten test pada pierwszy i mówi wprost, co się stało.

Podział ról w tych testach:
- `db_session` (fixture z `conftest.py`) → rola **właściciela**, widzi wszystko,
  służy do setupu i do porównania „ile jest naprawdę";
- `AsyncSessionLocal` → rola **aplikacji**, ta sama, którą jedzie API.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.rls import current_user_id, set_current_user_id
from app.db.session import AsyncSessionLocal

EMAIL_A = "rls-a@example.com"
EMAIL_B = "rls-b@example.com"
PASSWORD = "correct-password-1"


@pytest_asyncio.fixture(autouse=True)
async def _reset_user_context() -> AsyncGenerator[None, None]:
    """`ContextVar` jest per zadanie asyncio, ale pytest-asyncio potrafi
    dzielić pętlę między testami — zostawiony kontekst przeciekłby do
    sąsiedniego testu i dał mu cudze uprawnienia."""
    yield
    set_current_user_id(None)


async def _register_and_login(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user_id: str = r.json()["id"]
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return user_id, r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_portfolio(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/portfolios", json={"name": name, "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


async def _count(session: AsyncSession, table: str) -> Any:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()


async def test_rola_aplikacji_nie_omija_polityk(db_session: AsyncSession) -> None:
    """Warunek konieczny wszystkich pozostałych testów w tym pliku.

    Bez osobnej roli bez `BYPASSRLS` i bez własności tabel polityki nie
    działają — a nie działają **cicho**, więc reszta suity dalej byłaby
    zielona. Ten test jest po to, żeby taka regresja miała twarz.
    """
    assert get_settings().database_url_app, (
        "DATABASE_URL_APP jest pusty — API łączy się rolą właściciela i RLS nie obowiązuje"
    )

    async with AsyncSessionLocal() as app_session:
        role = (await app_session.execute(text("SELECT current_user"))).scalar()
        attrs = (
            await app_session.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()

    owner = (await db_session.execute(text("SELECT current_user"))).scalar()
    assert role != owner, "aplikacja i właściciel to ta sama rola — polityki są omijane"
    assert attrs == (False, False), f"rola {role} omija RLS: superuser/bypassrls = {attrs}"


async def test_sesja_bez_app_user_id_widzi_zero_wierszy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Kryterium akceptacyjne kroku 44 z planu etapu 8.

    Brak kontekstu ma znaczyć **niewidoczność**, nie „pokaż wszystko":
    `NULLIF(current_setting(...), '')::uuid` daje `NULL`, a porównanie
    z `NULL` nie przepuszcza żadnego wiersza.
    """
    _, token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token, "Portfel RLS")
    await client.post("/api/tags", json={"name": "rls"}, headers=_auth(token))
    await client.post("/api/watchlists", json={"name": "rls"}, headers=_auth(token))

    # Właściciel widzi, że dane fizycznie są.
    assert await _count(db_session, "portfolios") >= 1
    assert await _count(db_session, "tags") >= 1
    assert await _count(db_session, "watchlists") >= 1

    set_current_user_id(None)
    async with AsyncSessionLocal() as anonymous:
        assert await _count(anonymous, "portfolios") == 0
        assert await _count(anonymous, "tags") == 0
        assert await _count(anonymous, "watchlists") == 0
        # Także pojedynczy wiersz po znanym ID — polityka działa na `WHERE`,
        # nie na „liście wszystkiego".
        row = (
            await anonymous.execute(
                text("SELECT id FROM portfolios WHERE id = :pid"), {"pid": portfolio_id}
            )
        ).scalar()
        assert row is None


async def test_kontekst_uzytkownika_pokazuje_tylko_jego_wiersze(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Dwóch użytkowników, jedna baza, ta sama rola techniczna."""
    user_a, token_a = await _register_and_login(client, EMAIL_A)
    user_b, token_b = await _register_and_login(client, EMAIL_B)
    await _create_portfolio(client, token_a, "Portfel A")
    await _create_portfolio(client, token_b, "Portfel B")

    assert await _count(db_session, "portfolios") == 2

    set_current_user_id(user_a)
    async with AsyncSessionLocal() as session_a:
        names = (await session_a.execute(text("SELECT name FROM portfolios"))).scalars().all()
    assert names == ["Portfel A"]

    set_current_user_id(user_b)
    async with AsyncSessionLocal() as session_b:
        names = (await session_b.execute(text("SELECT name FROM portfolios"))).scalars().all()
    assert names == ["Portfel B"]


async def test_pozycje_dziedzicza_wlasciciela_po_portfelu(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`holdings` nie ma `user_id` — polityka idzie przez `portfolio_id`.

    Podzapytanie do `portfolios` samo podlega swojej polityce, więc cudza
    pozycja jest niewidoczna nawet przy znanym `portfolio_id`.
    """
    user_a, token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a, "Portfel A")

    asset_id = (
        await db_session.execute(text("SELECT id FROM assets WHERE is_active LIMIT 1"))
    ).scalar()
    assert asset_id is not None, "seed słownika jest wymagany do tego testu"
    resp = await client.post(
        f"/api/portfolios/{portfolio_a}/holdings",
        json={"asset_id": str(asset_id), "quantity": "1"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 201, resp.text

    # Sesja bez kontekstu: pozycja nie istnieje, mimo że fizycznie jest.
    set_current_user_id(None)
    async with AsyncSessionLocal() as anonymous:
        assert await _count(anonymous, "holdings") == 0
    assert await _count(db_session, "holdings") == 1


async def test_kontekst_nie_przecieka_miedzy_sesjami(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`SET LOCAL`, nie `SET` — inaczej pula połączeń przeniosłaby
    `app.user_id` na następne żądanie, czyli na innego użytkownika."""
    user_a, token_a = await _register_and_login(client, EMAIL_A)
    await _create_portfolio(client, token_a, "Portfel A")

    set_current_user_id(user_a)
    async with AsyncSessionLocal() as session_a:
        assert await _count(session_a, "portfolios") == 1
        await session_a.commit()

    # To samo połączenie wraca z puli do sesji bez kontekstu.
    set_current_user_id(None)
    async with AsyncSessionLocal() as anonymous:
        assert await _count(anonymous, "portfolios") == 0
        assert (
            await anonymous.execute(text("SELECT current_setting('app.user_id', true)"))
        ).scalar() in ("", None)

    assert current_user_id.get() == ""


async def test_ai_fund_session_dziedziczy_wlasciciela_po_portfelu(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`ai_fund_sessions` (ADR-104, Etap AI-1) — ten sam wzorzec co `holdings`:
    brak `user_id`, polityka idzie przez `portfolio_id`. Endpointów jeszcze
    nie ma (Etap AI-2), więc setup jest bezpośrednim `INSERT`-em, tak jak
    zrobiłby to worker/serwis w kolejnym etapie.
    """
    user_a, token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a, "Portfel A")

    await db_session.execute(
        text("INSERT INTO ai_fund_sessions (portfolio_id) VALUES (:pid)"),
        {"pid": portfolio_a},
    )
    await db_session.commit()

    set_current_user_id(None)
    async with AsyncSessionLocal() as anonymous:
        assert await _count(anonymous, "ai_fund_sessions") == 0

    set_current_user_id(user_a)
    async with AsyncSessionLocal() as owner:
        assert await _count(owner, "ai_fund_sessions") == 1
    assert await _count(db_session, "ai_fund_sessions") == 1


async def test_ai_agent_log_dziedziczy_wlasciciela_przez_sesje(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`ai_agent_logs` jest własnością sesji, która sama jest własnością
    portfela — dwupoziomowy łańcuch podzapytań (`_OWNED_VIA_PARENT`).
    Sprawdza, że polityka `ai_fund_sessions` nie blokuje podzapytania
    użytego przez politykę `ai_agent_logs` (rola aplikacji, nie właściciela).
    """
    user_a, token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a, "Portfel A")

    session_id = (
        await db_session.execute(
            text(
                "INSERT INTO ai_fund_sessions (portfolio_id) VALUES (:pid) RETURNING id"
            ),
            {"pid": portfolio_a},
        )
    ).scalar()
    await db_session.execute(
        text(
            "INSERT INTO ai_agent_logs (session_id, agent_type, parsed_data) "
            "VALUES (:sid, 'research', '{}'::jsonb)"
        ),
        {"sid": session_id},
    )
    await db_session.commit()

    set_current_user_id(None)
    async with AsyncSessionLocal() as anonymous:
        assert await _count(anonymous, "ai_agent_logs") == 0

    set_current_user_id(user_a)
    async with AsyncSessionLocal() as owner:
        assert await _count(owner, "ai_agent_logs") == 1
    assert await _count(db_session, "ai_agent_logs") == 1
