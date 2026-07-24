---
name: alembic-migracja
description: Procedura tworzenia i weryfikacji migracji Alembic w projekcie Portfel v2, w tym pułapki autogenerate, NUMERIC(20,8), indeksy i seed słownika rynków. Użyj przy każdej zmianie modelu danych, dodaniu tabeli lub kolumny, zmianie indeksu, a także gdy migracja nie przechodzi albo trzeba ją wycofać.
---

# Migracje Alembic

## Procedura

```bash
make revision m="dodaj markets i assets.market_code"
# przeczytaj wygenerowany plik — zawsze
make migrate
alembic downgrade -1
make migrate
```

Migracja bez działającego `downgrade()` jest niedokończona.

## Czego autogenerate nie wykryje (sprawdź ręcznie)

| Element | Co zrobić |
|---|---|
| Precyzja `NUMERIC(20,8)` | dopisz jawnie, autogenerate potrafi zgubić skalę |
| Indeksy częściowe i wyrażeniowe | `op.create_index(..., postgresql_where=...)` ręcznie |
| `CHECK` (np. `quantity >= 0`) | `op.create_check_constraint` ręcznie |
| `ON DELETE CASCADE` | sprawdź `ondelete` w każdym FK od `users` w dół |
| Zmiana typu na niepustej tabeli | rozbij na: dodaj kolumnę → przepisz dane → usuń starą |
| Dane słownikowe (`markets`) | osobna migracja danych albo `make seed`, nie mieszaj ze schematem |

## Szablon migracji danych

```python
def upgrade() -> None:
    markets = sa.table("markets",
        sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("timezone", sa.String), sa.column("eod_time", sa.Time))
    op.bulk_insert(markets, [
        {"code": "GPW",  "name": "Giełda Papierów Wartościowych", "timezone": "Europe/Warsaw",  "eod_time": time(18, 30)},
        {"code": "US",   "name": "NYSE/NASDAQ",                   "timezone": "America/New_York", "eod_time": time(23, 15)},
        {"code": "CRYPTO","name": "Krypto (24/7)",               "timezone": "UTC",            "eod_time": time(0, 30)},
    ])

def downgrade() -> None:
    op.execute("DELETE FROM markets WHERE code IN ('GPW','US','CRYPTO')")
```

Pełna lista rynków: `docs/slownik-rynkow.md`.

## Kolejność tworzenia tabel (zależności FK)

```
users → portfolios → holdings
markets ⇄ assets      (cykl: markets.index_asset_id → assets.id, assets.market_code → markets.code)
assets → prices, asset_source_map, asset_tags, news_assets
portfolios → portfolio_valuations
```

Cykl `markets ⇄ assets` rozwiązujesz tak: najpierw `markets` bez `index_asset_id`, potem `assets` z FK do `markets`, potem `ALTER TABLE markets ADD COLUMN index_asset_id` z FK. Nie próbuj tworzyć obu naraz.

## Konwencja nazw

`versions/<data>_<slug>.py`, np. `20260801_holdings_and_markets.py`. Komunikat rewizji po polsku, opisowy: co i po co.
