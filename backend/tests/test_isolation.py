"""Mechanizm testowania izolacji danych między użytkownikami (ADR-002, plan krok 15).

To jest **harness**, nie zestaw testów na konkretne zasoby: introspekcja
`app.routes` znajduje trasy przyjmujące identyfikator zasobu (patrz
`RESOURCE_PARAMS`) i dla każdej sprawdza, że użytkownik B nie może dotknąć
zasobu użytkownika A. Zobacz `.claude/skills/izolacja-danych/SKILL.md` —
to jest specyfikacja tego pliku.

Stan na etap 3: tabele `portfolios`/`holdings` już istnieją (od etapu 3),
ale żaden endpoint jeszcze nie przyjmuje ich ID z path przez `get_owned_*`
(CRUD portfeli/pozycji to etap 5) — `watchlists`/`tags` nie istnieją wcale
(Faza 2). `protected_routes(app)` zwraca więc listę pustą i
`test_user_b_cannot_touch_user_a_resources` dostaje zero przypadków z
`pytest.mark.parametrize` — pytest generuje z tego jeden syntetyczny
przypadek `[NOTSET]` i raportuje go jako **skipped** (nie błąd, nie
failure; zweryfikowane empirycznie: `pytest -v` → `1 skipped`). Mechanizm
zacznie automatycznie łapać trasy, gdy w przyszłych etapach powstaną
endpointy z `Depends(get_owned_portfolio)` itd. — bez przepisywania tego
pliku, wystarczy że nowy typ zasobu trafi do `RESOURCE_PARAMS` (patrz skill).

Fixtures `user_a_fixtures`/`token_b` są zbudowane minimalnie: dwoje
zarejestrowanych i zalogowanych użytkowników. `user_a_fixtures.ids` — słownik
podstawiany przez `route.path.format(**ids)` — jest dziś pusty, bo nie
znamy jeszcze nazw/kształtu przyszłych identyfikatorów zasobów (spekulacja
ponad to, co wynika ze skila, jest świadomie pominięta).

TODO(etap 3/5): gdy powstanie pierwszy `get_owned_*` (najpewniej
`get_owned_portfolio` przy CRUD holdings), rozbudować `user_a_fixtures` o
utworzenie portfela użytkownika A (przez HTTP albo `db_session`) i dopisać
np. `"portfolio_id": str(portfolio.id)` do `ids`, żeby `route.path.format`
miał czym wypełnić placeholdery.

Test „pozytywny" ze skila („użytkownik A na własnych zasobach dostaje 2xx")
nie ma dziś czego dotyczyć — nie istnieje żaden chroniony zasób. Najbliższy
sensowny odpowiednik na tym etapie: `get_current_user` faktycznie odróżnia
użytkownika A od B (różne `user.id` dla różnych tokenów) — to fundament, na
którym `get_owned_*` będzie budować izolację, gdy powstanie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.main import app

# Nazwy parametrów ścieżki oznaczające zasób należący do użytkownika. Nowy
# typ zasobu (nowa zależność `get_owned_*` w `core/deps.py`) = nowy wpis
# tutaj, inaczej jego trasy nie trafią do parametryzacji poniżej i nie będą
# chronione przez ten mechanizm.
RESOURCE_PARAMS = {"portfolio_id", "holding_id", "watchlist_id", "tag_id"}


def protected_routes(app_: Any) -> list[APIRoute]:
    """Zwraca trasy przyjmujące co najmniej jeden identyfikator zasobu.

    `app_: Any`, bo sygnatura odzwierciedla `izolacja-danych/SKILL.md`
    (`protected_routes(app)`) — typowanie `FastAPI` nie dodaje tu nic ponad
    to, co już widać z użycia (`app_.routes`), a `Any` unika sztywnego
    importu typu tylko dla adnotacji jednej pomocniczej funkcji testowej.

    Introspekcja `app.routes` — nowy endpoint z `Depends(get_owned_*)` trafia
    tu automatycznie, bez dopisywania testu ręcznie.
    """
    return [
        route
        for route in app_.routes
        if isinstance(route, APIRoute) and RESOURCE_PARAMS & set(route.param_convertors)
    ]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class UserAFixtures:
    """Dane użytkownika A potrzebne do budowy URL-i chronionych zasobów.

    `ids` to słownik użyty jako `route.path.format(**ids)`. Dziś pusty —
    patrz TODO w docstringu modułu.
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
async def user_a_fixtures(client: AsyncClient) -> UserAFixtures:
    """Użytkownik A, zalogowany — gotowy do (w przyszłości) posiadania zasobów."""
    token = await _register_and_login(client, "izolacja-a@example.com", "correct-password-1")
    return UserAFixtures(token=token)


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

    Parametryzacja jest dziś (etap 3) pusta — brak jakiegokolwiek endpointu
    z identyfikatorem zasobu w `RESOURCE_PARAMS`. Pytest generuje z tego
    jeden syntetyczny przypadek `[NOTSET]` zgłaszany jako **skipped** (nie
    error, nie failure) — plik i CI mimo to przechodzą. Zacznie łapać
    realne trasy automatycznie od etapu 5, gdy powstaną
    `get_owned_portfolio`/`get_owned_holding`.
    """
    url = route.path.format(**user_a_fixtures.ids)
    for method in route.methods - {"HEAD", "OPTIONS"}:
        resp = await client.request(method, url, headers=_auth_headers(token_b), json={})
        assert resp.status_code in (404, 422), (
            f"{method} {route.path} przecieka dane cudzego zasobu: {resp.status_code}"
        )


async def test_current_user_dependency_distinguishes_users_a_and_b(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Odpowiednik testu „pozytywnego" ze skila, dostępny na tym etapie.

    Skill wymaga testu, że użytkownik A na własnych zasobach dostaje 2xx —
    inaczej parametryzowany test wyżej przechodziłby nawet przy całkowicie
    zepsutym API. Dziś nie ma jeszcze żadnego chronionego zasobu (portfolio/
    holding), więc weryfikujemy najbliższy sensowny fragment tego mechanizmu:
    `get_current_user` faktycznie zwraca różnych, poprawnych użytkowników dla
    różnych tokenów — to fundament, na którym `get_owned_*` będzie budować
    izolację, gdy powstanie w etapie 3/5.
    """
    token_a = await _register_and_login(client, "pozytywny-a@example.com", "correct-password-1")
    token_b_local = await _register_and_login(
        client, "pozytywny-b@example.com", "correct-password-1"
    )

    user_a = await get_current_user(db=db_session, authorization=f"Bearer {token_a}")
    user_b = await get_current_user(db=db_session, authorization=f"Bearer {token_b_local}")

    assert user_a.id != user_b.id
    assert user_a.email == "pozytywny-a@example.com"
    assert user_b.email == "pozytywny-b@example.com"
