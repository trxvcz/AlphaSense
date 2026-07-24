---
name: fastapi-modul
description: Struktura i konwencje modułu backendu FastAPI w projekcie Portfel v2 — podział na routes/schemas/service/models, obsługa Decimal, błędy domenowe, cache. Użyj gdy tworzysz nowy moduł backendu, dodajesz endpoint, refaktorujesz warstwy albo zastanawiasz się, gdzie umieścić logikę lub jak serializować kwoty.
---

# Moduł backendu FastAPI

## Układ katalogu

```
backend/app/modules/<nazwa>/
  __init__.py
  routes.py     # tylko: routing, walidacja, autoryzacja, wywołanie serwisu
  schemas.py    # Pydantic v2: wejście i wyjście
  service.py    # logika domenowa, czysta na ile się da
  repository.py # zapytania SQLAlchemy
  models.py     # modele ORM (jeśli moduł je posiada)
```

Rejestracja w `main.py`: `app.include_router(router, prefix="/api")`.

## Warstwy — twarda granica

| Warstwa | Wolno | Nie wolno |
|---|---|---|
| routes | `Depends`, walidacja, mapowanie na schemat odpowiedzi | SQL, obliczenia, `AsyncSession` bez potrzeby |
| service | logika, orkiestracja, cache | konstrukcje HTTP (`HTTPException`) |
| repository | SQLAlchemy, zapytania | logika biznesowa |

Serwis rzuca wyjątki domenowe z `core/errors.py` (`NotFoundError`, `ConflictError`, `ValidationError`, `ProviderUnavailableError`). Mapowanie na HTTP jest w jednym `exception_handler` w `main.py`.

## Kwoty

```python
from decimal import Decimal
from pydantic import BaseModel, field_serializer

class HoldingOut(BaseModel):
    id: UUID
    symbol: str
    quantity: Decimal
    value_pln: Decimal

    @field_serializer("quantity", "value_pln")
    def ser_decimal(self, v: Decimal) -> str:
        return format(v, "f")     # string, nigdy float
```

Zaokrąglanie do prezentacji robi frontend. Backend liczy z pełną precyzją i zaokrągla wyłącznie na końcu, jawnie, przez `quantize` z `ROUND_HALF_UP`.

## Cache

```python
key = f"allocation:{portfolio.id}:{by}:{portfolio.holdings_version}:{eod_date}"
```

`holdings_version` to znacznik ostatniej zmiany składu portfela (kolumna aktualizowana przy każdej zmianie `holdings`). Dzięki temu **nie ma inwalidacji** — zmiana składu zmienia klucz. TTL i tak ustaw (np. 24 h), żeby Redis nie puchł.

## Test modułu

```python
async def test_allocation_by_class(client, portfolio_with_holdings, token):
    r = await client.get(f"/api/portfolios/{portfolio_with_holdings.id}/allocation?by=class",
                         headers=auth(token))
    assert r.status_code == 200
    assert sum(Decimal(x["weight"]) for x in r.json()["buckets"]) == Decimal("1")
```

Suma wag zawsze 1 (z tolerancją zaokrąglenia zdefiniowaną w jednym miejscu) — to najlepszy pojedynczy test poprawności alokacji.
