---
name: izolacja-danych
description: Wzorzec autoryzacji zasobowej i testowania izolacji danych między użytkownikami w projekcie Portfel v2. Użyj ZAWSZE gdy dodajesz lub zmieniasz endpoint przyjmujący identyfikator zasobu (portfel, pozycja, watchlista, tag), gdy piszesz zależności FastAPI, gdy weryfikujesz bezpieczeństwo API albo gdy pojawia się pytanie o RLS, wielodostęp, 403/404 lub „czy użytkownik A widzi dane użytkownika B".
---

# Izolacja danych między użytkownikami

Najpoważniejsza klasa błędów w tej aplikacji: użytkownik A czyta portfel użytkownika B przez podmianę ID w URL. Ta procedura ma temu zapobiec systemowo, a nie przez czujność przy każdym endpointcie.

## Zasada

**Żaden handler nie dostaje surowego identyfikatora z path.** Handler dostaje **obiekt**, który zależność już zweryfikowała jako należący do zalogowanego użytkownika.

## Wzorzec zależności

```python
# core/deps.py
async def get_owned_portfolio(
    portfolio_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Portfolio:
    portfolio = await db.scalar(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    if portfolio is None:
        raise NotFoundError("portfolio")   # 404, nie 403 — nie ujawniamy istnienia
    return portfolio


async def get_owned_holding(
    holding_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Holding:
    holding = await db.scalar(
        select(Holding)
        .join(Portfolio)
        .where(Holding.id == holding_id, Portfolio.user_id == user.id)
    )
    if holding is None:
        raise NotFoundError("holding")
    return holding
```

Użycie:

```python
@router.get("/portfolios/{portfolio_id}/allocation")
async def get_allocation(
    portfolio: Portfolio = Depends(get_owned_portfolio),   # ← obiekt, nie ID
    by: AllocationDimension = Query(AllocationDimension.CLASS),
):
    return await service.allocation(portfolio, by)
```

**Antywzorzec** (nie przechodzi review):

```python
@router.get("/portfolios/{portfolio_id}/allocation")
async def get_allocation(portfolio_id: UUID, user: User = Depends(get_current_user)):
    ...  # weryfikacja własności zrobiona (albo nie) w serwisie
```

## Konwencja kodów odpowiedzi

Cudzy zasób → **404**, konsekwentnie na wszystkich trasach. 403 zarezerwowane na przypadki, gdzie zasób jest jawnie współdzielony, a brakuje uprawnienia. Nigdy nie zwracaj komunikatu ujawniającego, że zasób istnieje, ale należy do kogoś innego.

## Test parametryzowany (obowiązkowy w CI)

Test przechodzi po **wszystkich** zarejestrowanych trasach automatycznie — nowy endpoint jest pokryty bez dopisywania testu.

```python
# tests/test_isolation.py
RESOURCE_PARAMS = {"portfolio_id", "holding_id", "watchlist_id", "tag_id"}

def protected_routes(app) -> list[APIRoute]:
    return [
        r for r in app.routes
        if isinstance(r, APIRoute) and RESOURCE_PARAMS & set(r.param_convertors)
    ]

@pytest.mark.parametrize("route", protected_routes(app), ids=lambda r: f"{r.methods}:{r.path}")
async def test_user_b_cannot_touch_user_a_resources(route, client, user_a_fixtures, token_b):
    url = route.path.format(**user_a_fixtures.ids)
    for method in route.methods - {"HEAD", "OPTIONS"}:
        resp = await client.request(method, url, headers=auth(token_b), json={})
        assert resp.status_code in (404, 422), (
            f"{method} {route.path} przecieka dane: {resp.status_code}"
        )
```

Dodatkowo test „pozytywny": użytkownik A na własnych zasobach dostaje 2xx — inaczej test przechodziłby przy całkowicie zepsutym API.

## Lista kontrolna przy nowym endpointcie

- [ ] parametr ścieżki przez `get_owned_*`
- [ ] nowy typ zasobu dopisany do `RESOURCE_PARAMS`
- [ ] zapytania listujące filtrują po `user_id` (nie polegaj na tym, że ID jest „nieodgadywalne")
- [ ] agregacje i cache mają `user_id`/`portfolio_id` w kluczu
- [ ] `pytest tests/test_isolation.py` zielone

## Faza 2: RLS

W etapie 44 dochodzi druga warstwa: polityki Row Level Security w Postgresie po `user_id`, sesja aplikacyjna ustawia `SET LOCAL app.user_id`. Worker działa na roli z `BYPASSRLS`. RLS **nie zastępuje** zależności `get_owned_*` — to obrona w głąb.
