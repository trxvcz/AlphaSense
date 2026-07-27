"""Mechanizm testowania izolacji danych między użytkownikami (ADR-002, plan krok 15).

To jest **harness**, nie zestaw testów na konkretne zasoby: introspekcja
`app.routes` znajduje trasy przyjmujące identyfikator zasobu (patrz
`RESOURCE_PARAMS`) i dla każdej sprawdza, że użytkownik B nie może dotknąć
zasobu użytkownika A. Zobacz `.claude/skills/izolacja-danych/SKILL.md` —
to jest specyfikacja tego pliku.

Stan na etap 5: `get_owned_portfolio`/`get_owned_holding` (`core/deps.py`)
i ich pierwsi konsumenci (`modules/portfolio/routes.py`, plan kroki 25-28)
już istnieją, więc `protected_routes(app)` łapie realne trasy
(`/portfolios/{portfolio_id}...`, `/holdings/{holding_id}`) automatycznie —
bez zmian w tym pliku poza wypełnieniem `user_a_fixtures.ids` (patrz niżej).
`watchlists`/`tags` nadal nie istnieją (Faza 2).

`user_a_fixtures` tworzy dla użytkownika A jeden portfel i jedną pozycję
**przez `service`/`repository` bezpośrednio, nie przez HTTP** — ten harness
testuje właśnie endpointy CRUD portfeli/pozycji, więc nie powinien zależeć
od ich poprawności, żeby ustawić własne dane wejściowe (gdyby np.
`POST /portfolios` samo miało dziurę izolacji, harness zbudowany na nim
mógłby jej nie złapać). Aktywo potrzebne do pozycji jest tymczasowe
(losowy sufiks symbolu, jak w `tests/integration/test_assets_search.py`),
na rynku `GPW` (zakłada, że słownik `markets` zawiera `GPW` — jak
`tests/integration/test_meta_freshness.py`), sprzątane po teście.

Test „pozytywny" ze skila („użytkownik A na własnych zasobach dostaje 2xx")
ma teraz realny chroniony zasób do sprawdzenia:
`test_user_a_can_access_own_resources` obok istniejącego
`test_current_user_dependency_distinguishes_users_a_and_b`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.main import app
from app.modules.marketdata.models import Asset
from app.modules.portfolio import service as portfolio_service

# Nazwy parametrów ścieżki oznaczające zasób należący do użytkownika. Nowy
# typ zasobu (nowa zależność `get_owned_*` w `core/deps.py`) = nowy wpis
# tutaj, inaczej jego trasy nie trafią do parametryzacji poniżej i nie będą
# chronione przez ten mechanizm.
RESOURCE_PARAMS = {"portfolio_id", "holding_id", "watchlist_id", "tag_id"}


def protected_routes(app_: Any) -> list[RouteContext]:
    """Zwraca trasy przyjmujące co najmniej jeden identyfikator zasobu.

    `app_: Any`, bo sygnatura odzwierciedla `izolacja-danych/SKILL.md`
    (`protected_routes(app)`) — typowanie `FastAPI` nie dodaje tu nic ponad
    to, co już widać z użycia (`app_.routes`), a `Any` unika sztywnego
    importu typu tylko dla adnotacji jednej pomocniczej funkcji testowej.

    **Uwaga wersji FastAPI (0.139.2):** `app.routes` już NIE zawiera
    spłaszczonych `APIRoute` bezpośrednio — `include_router` opakowuje je w
    `_IncludedRouter` (leniwe rozwiązywanie efektywnych tras, cache po
    wersji routera). Naiwne `isinstance(route, APIRoute)` na `app.routes`
    (wzorzec ze skila, pisany pod starszą architekturę FastAPI) milcząco
    zwracało pustą listę — sparametryzowany test niżej „przechodził" jako
    same `skipped`, nie sprawdzając niczego (złapane przy aktywacji tego
    harnessu w etapie 5: zanim istniały trasy z `portfolio_id`/`holding_id`,
    pusta lista była nie do odróżnienia od tego bugu). `iter_route_contexts`
    to udokumentowany w `fastapi.routing` sposób na spłaszczenie efektywnych
    tras (łącznie z zagnieżdżonymi routerami) do obiektów `RouteContext`,
    które przez `__getattr__` delegują `path`/`methods`/`param_convertors`
    do oryginalnej `APIRoute` — używane tu zamiast bezpośredniej iteracji
    po `app.routes`.
    """
    return [
        ctx
        for ctx in iter_route_contexts(app_.routes)
        if isinstance(ctx.original_route, APIRoute) and RESOURCE_PARAMS & set(ctx.param_convertors)
    ]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class UserAFixtures:
    """Dane użytkownika A potrzebne do budowy URL-i chronionych zasobów.

    `ids` to słownik użyty jako `route.path.format(**ids)` — klucze muszą
    odpowiadać nazwom parametrów ścieżki (`portfolio_id`, `holding_id`,
    patrz `RESOURCE_PARAMS`).
    """

    token: str
    ids: dict[str, str] = field(default_factory=dict)


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    register_resp = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert register_resp.status_code == 201, register_resp.text

    login_resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text

    token: str = login_resp.json()["access_token"]
    return token


@pytest_asyncio.fixture
async def user_a_fixtures(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[UserAFixtures, None]:
    """Użytkownik A, zalogowany, właściciel jednego portfela i jednej
    pozycji — utworzonych przez `service`/`repository`, nie przez HTTP
    (patrz docstring modułu)."""
    token = await _register_and_login(client, "izolacja-a@example.com", "correct-password-1")
    user = await get_current_user(db=db_session, authorization=f"Bearer {token}")

    suffix = uuid.uuid4().hex[:8]
    asset = Asset(
        symbol=f"ISO{suffix}",
        name=f"Izolacja Test {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    portfolio = await portfolio_service.create_portfolio(
        db_session, user_id=user.id, name="Portfel izolacji", type_="standard"
    )
    valued_holding = await portfolio_service.create_holding(
        db_session,
        portfolio,
        asset_id=asset.id,
        quantity=Decimal("1"),
        avg_cost=None,
        cost_currency=None,
        note=None,
    )

    yield UserAFixtures(
        token=token,
        ids={
            "portfolio_id": str(portfolio.id),
            "holding_id": str(valued_holding.holding.id),
        },
    )

    # `Holding.asset_id` nie kaskaduje z `assets` (`models.py`, docstring
    # `Holding`) — usuwamy najpierw portfel (kaskaduje na `holdings` przez
    # `ON DELETE CASCADE`), dopiero potem aktywo tymczasowe, inaczej `DELETE
    # FROM assets` wywaliłby się na wciąż istniejącym FK z `holdings`.
    await portfolio_service.delete_portfolio(db_session, portfolio)
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


@pytest_asyncio.fixture
async def token_b(client: AsyncClient) -> str:
    """Użytkownik B — ten, który nie powinien móc dotknąć zasobów A."""
    return await _register_and_login(client, "izolacja-b@example.com", "correct-password-1")


@pytest.mark.parametrize(
    "route",
    protected_routes(app),
    ids=lambda r: f"{sorted(r.methods)}:{r.path}",
)
async def test_user_b_cannot_touch_user_a_resources(
    route: APIRoute,
    client: AsyncClient,
    user_a_fixtures: UserAFixtures,
    token_b: str,
) -> None:
    """Użytkownik B dostaje 404 (nigdy dane) na każdej trasie zasobowej A.

    Konwencja projektu (skill `izolacja-danych`): cudzy zasób -> 404, nigdy
    403 — nie zdradzamy istnienia zasobu. 422 jest dopuszczalne, gdy walidacja
    Pydantic ciała żądania wywala się przed dotarciem do `get_owned_*`.

    Parametryzacja łapie od etapu 5 realne trasy modułu `portfolio`
    (`/portfolios/{portfolio_id}...`, `/holdings/{holding_id}`) — nowy typ
    zasobu w przyszłości wymaga tylko dopisania do `RESOURCE_PARAMS`
    (patrz skill), bez zmian w tym teście.
    """
    url = route.path.format(**user_a_fixtures.ids)
    for method in route.methods - {"HEAD", "OPTIONS"}:
        resp = await client.request(method, url, headers=_auth_headers(token_b), json={})
        assert resp.status_code in (404, 422), (
            f"{method} {route.path} przecieka dane cudzego zasobu: {resp.status_code}"
        )


async def test_user_a_can_access_own_resources(
    client: AsyncClient, user_a_fixtures: UserAFixtures
) -> None:
    """Test „pozytywny" wymagany przez skill: właściciel dostaje 2xx na
    własnych zasobach — inaczej `test_user_b_cannot_touch_user_a_resources`
    przechodziłby nawet przy całkowicie zepsutym API (np. gdyby wszystko
    zwracało 404, łącznie z żądaniami właściciela)."""
    portfolio_id = user_a_fixtures.ids["portfolio_id"]

    get_resp = await client.get(
        f"/api/portfolios/{portfolio_id}", headers=_auth_headers(user_a_fixtures.token)
    )
    assert get_resp.status_code == 200

    holdings_resp = await client.get(
        f"/api/portfolios/{portfolio_id}/holdings", headers=_auth_headers(user_a_fixtures.token)
    )
    assert holdings_resp.status_code == 200
    assert len(holdings_resp.json()) == 1


async def test_current_user_dependency_distinguishes_users_a_and_b(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """`get_current_user` zwraca różnych, poprawnych użytkowników dla
    różnych tokenów — fundament, na którym `get_owned_*` buduje izolację."""
    token_a = await _register_and_login(client, "pozytywny-a@example.com", "correct-password-1")
    token_b_local = await _register_and_login(
        client, "pozytywny-b@example.com", "correct-password-1"
    )

    user_a = await get_current_user(db=db_session, authorization=f"Bearer {token_a}")
    user_b = await get_current_user(db=db_session, authorization=f"Bearer {token_b_local}")

    assert user_a.id != user_b.id
    assert user_a.email == "pozytywny-a@example.com"
    assert user_b.email == "pozytywny-b@example.com"
