# Model danych

Rozwinięcie sekcji 5 projektu systemu. Przy każdej zmianie schematu aktualizuj ten plik razem z migracją.

## Zasady globalne

- Kwoty i ilości: `NUMERIC(20,8)`. **Nigdy `float`, nigdy `double precision`.**
- Daty rynkowe: `DATE`. Znaczniki czasu: `TIMESTAMPTZ` (aplikacja w UTC, prezentacja w Europe/Warsaw).
- Identyfikatory: `UUID` (`gen_random_uuid()`), poza tabelami słownikowymi z naturalnym kluczem (`markets.code`, `fx_rates.currency`).
- `ON DELETE CASCADE` na całej ścieżce od `users` w dół.
- Kwoty w API serializowane jako **stringi dziesiętne**.

## Tabele

| Tabela | Klucz | Istotne kolumny | Uwagi |
|---|---|---|---|
| `users` | id | email (unique), password_hash, created_at | argon2id |
| `refresh_tokens` | id | user_id, token_hash, expires_at, revoked_at, replaced_by | rotacja, wykrywanie ponownego użycia |
| `portfolios` | id | user_id, name, type, holdings_version | `holdings_version` = znacznik do klucza cache |
| `holdings` | id | portfolio_id, asset_id, quantity, avg_cost, cost_currency, valid_from, note | `UNIQUE(portfolio_id, asset_id)` |
| `assets` | id | symbol, name, asset_class, **market_code**, currency, isin, sector, country, region, metadata_source, is_active | sektor/kraj z dostawcy, override użytkownika ma pierwszeństwo |
| `markets` | code | name, index_asset_id, timezone, eod_time | ADR-102, jedno źródło prawdy |
| `asset_source_map` | (asset_id, provider) | provider_symbol, priority | warunek działania fallbacku |
| `prices` | (asset_id, date) | open, high, low, close, **close_adj**, volume | wycena zawsze z `close_adj` |
| `fx_rates` | (currency, date) | rate_pln | NBP tabela A; lookup `max(date) <= D` |
| `portfolio_valuations` | (portfolio_id, date) | value_pln, **composition_change** | ADR-101, bez kolumny przepływów |
| `ingestion_runs` | id | market_code, started_at, finished_at, provider, assets_total, assets_ok, status, error | podstawa `/meta/freshness` i alertów |
| `watchlists`, `watchlist_items` | | | Faza 2 |
| `tags`, `asset_tags` | | | Faza 2 |
| `news`, `news_assets` | | | Faza 3 |
| `dividend_events` | | | Faza 3 |

## Indeksy

```sql
CREATE INDEX ON holdings (portfolio_id);
CREATE INDEX ON prices (asset_id, date DESC);
CREATE INDEX ON assets (market_code);
CREATE INDEX ON assets (symbol);
CREATE INDEX ON portfolio_valuations (portfolio_id, date DESC);
CREATE INDEX ON ingestion_runs (market_code, started_at DESC);
CREATE INDEX ON news_assets (asset_id, published_at DESC);
```

## Ograniczenia

```sql
ALTER TABLE holdings ADD CONSTRAINT quantity_nonneg CHECK (quantity >= 0);
ALTER TABLE holdings ADD CONSTRAINT avg_cost_needs_currency
  CHECK (avg_cost IS NULL OR cost_currency IS NOT NULL);
ALTER TABLE prices  ADD CONSTRAINT close_adj_positive CHECK (close_adj > 0);
```

## Droga powrotu (sekcja 10 projektu)

Gdyby wróciły transakcje: `holdings` staje się projekcją z `transactions`, `portfolio_valuations` dostaje kolumnę przepływów, wraca ADR-006. Nic w tym schemacie tego nie blokuje — dlatego `valid_from` i `NUMERIC(20,8)` są od początku.
