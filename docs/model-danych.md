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
| `users` | id | email (unique), password_hash (**nullable**), created_at | argon2id; `password_hash IS NULL` = konto OAuth-only (Google, dopasowane po `email`) |
| `refresh_tokens` | id | user_id, token_hash, expires_at, revoked_at, replaced_by | rotacja, wykrywanie ponownego użycia |
| `portfolios` | id | user_id, name, type, holdings_version, **holdings_changed_at** | `holdings_version` = znacznik do klucza cache; `holdings_changed_at` (nullable) = data ostatniej mutacji `holdings`, podstawa `composition_change` w jobie snapshotów (etap 5, krok 27) |
| `holdings` | id | portfolio_id, asset_id, quantity, avg_cost, cost_currency, valid_from, note | `UNIQUE(portfolio_id, asset_id)` |
| `assets` | id | symbol, name, asset_class, **market_code**, currency, isin, sector, country, region, metadata_source, is_active | sektor/kraj z dostawcy, override użytkownika ma pierwszeństwo |
| `markets` | code | name, index_asset_id, timezone, eod_time | ADR-102, jedno źródło prawdy |
| `asset_source_map` | (asset_id, provider) | provider_symbol, priority | warunek działania fallbacku |
| `prices` | (asset_id, date) | open, high, low, close, **close_adj**, volume, source | wycena zawsze z `close_adj`; `source` = dostawca wiersza, `NULL` = sprzed migracji `926b382d1715` |
| `fx_rates` | (currency, date) | rate_pln | NBP tabela A; lookup `max(date) <= D` |
| `portfolio_valuations` | (portfolio_id, date) | value_pln, **composition_change** | ADR-101, bez kolumny przepływów |
| `ingestion_runs` | id | market_code, started_at, finished_at, provider, assets_total, assets_ok, status, error | podstawa `/meta/freshness` i alertów |
| `watchlists` | id | user_id, name, created_at; **UNIQUE (user_id, name)** | krok 43; unikalność nazwy **per użytkownik**, nie globalnie. `ON DELETE CASCADE` z `users` |
| `watchlist_items` | (watchlist_id, asset_id) | note, added_at | krok 43; klucz naturalny daje idempotentne „dodaj do listy". Kaskada tylko od `watchlists` — wygaszenie aktywa nie kasuje listy użytkownika. **Bez ilości i wyceny**: watchlista to nie portfel (CLAUDE.md #3.11) |
| `tags` | id | user_id, name, color, created_at; **UNIQUE (user_id, name)** | krok 43; `color` (`#rrggbb`) walidowany w Pydantic, nie w bazie — paleta należy do prezentacji i **nigdy nie jest jedynym nośnikiem informacji** (CLAUDE.md §21) |
| `asset_tags` | (tag_id, asset_id) | created_at | krok 43; tag wisi na **aktywie**, nie na pozycji — „dywidendowe" to cecha spółki, więc działa we wszystkich portfelach użytkownika. `assets` jest globalne, więc każdy odczyt powiązań jest zawężony przez `JOIN tags` po `tags.user_id` |
| `news` | id | title, url **UNIQUE**, source, published_at, fetched_at, content_hash **UNIQUE**, summary, sentiment, sentiment_source | krok 46; dwa ograniczenia unikalności, bo ta sama depesza PAP chodzi po serwisach pod różnymi URL-ami |
| `news_assets` | (news_id, asset_id) | published_at (zdenormalizowane), match_confidence | krok 46; `ON DELETE CASCADE` w obie strony, brak FK do `users` — newsy nie są własnością użytkownika. `match_confidence`: `source` (powiązanie podał dostawca pytany o symbol — fakt) albo `heuristic` (dopasowanie tekstu po naszej stronie — przybliżenie, UI ma je oznaczyć, CLAUDE.md #3.15). Domyślnie `heuristic`, bo pominięcie kolumny ma zaniżać deklarowaną pewność, nie zawyżać |
| `dividend_events` | id | asset_id, ex_date, record_date, pay_date, declaration_date, amount, currency, source, fetched_at; **UNIQUE (asset_id, ex_date)** | krok 47; zapis `ON CONFLICT DO UPDATE` — zapowiedziana kwota/data wypłaty bywa korygowana przed wypłatą, więc świeższa odpowiedź dostawcy wygrywa (odwrotnie niż przy `news`). Brak FK do `users`: zdarzenie nie jest własnością użytkownika, izolacja dzieje się przy odczycie. `amount` w walucie notowania, brutto — bez PLN i bez podatku (to nie jest wpis księgowy, Etap 21) |
| `nbp_reference_rates` | effective_from | rate, source, fetched_at | krok 41a; **wiersz = zmiana stopy (decyzja RPP), nie dzień** — NBP nie publikuje szeregu dziennego, więc obowiązywanie „do następnej zmiany" wynika z lookupu `max(effective_from) <= D` przy odczycie, jak w `fx_rates` (CLAUDE.md #3.5). `rate` to **ułamek roczny** (`0.03750000` = 3,75% p.a.), nie procent — źródło podaje procent z przecinkiem (`"3,75"`). Klucz główny jednokolumnowy: w danym dniu obowiązuje dokładnie jedna stopa referencyjna, więc nie potrzeba ani sztucznego `id`, ani osobnego `UNIQUE`, ani dodatkowego indeksu. Brak FK do `users` — dana makro nie jest własnością użytkownika. Źródło: `static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml` (`api.nbp.pl` **nie** wystawia stóp procentowych); świeżość liczona z `max(effective_from)`, **nigdy** z atrybutu `data_publikacji` w XML-u, który NBP ma zamrożony na 2015 roku |

## Indeksy

```sql
CREATE INDEX ON holdings (portfolio_id);
CREATE INDEX ON prices (asset_id, date DESC);
CREATE INDEX ON assets (market_code);
CREATE INDEX ON assets (symbol);
CREATE INDEX ON portfolio_valuations (portfolio_id, date DESC);
CREATE INDEX ON ingestion_runs (market_code, started_at DESC);
CREATE INDEX ON news_assets (asset_id, published_at DESC);
CREATE INDEX ON news (published_at DESC);
-- rosnąco, nie malejąco: kalendarz czyta najbliższe ex-daty od dziś w przód
CREATE INDEX ON dividend_events (asset_id, ex_date);
CREATE INDEX ON watchlists (user_id);
CREATE INDEX ON watchlist_items (asset_id);
CREATE INDEX ON tags (user_id);
CREATE INDEX ON asset_tags (asset_id);
```

## Ograniczenia

```sql
ALTER TABLE holdings ADD CONSTRAINT quantity_nonneg CHECK (quantity >= 0);
ALTER TABLE holdings ADD CONSTRAINT avg_cost_needs_currency
  CHECK (avg_cost IS NULL OR cost_currency IS NOT NULL);
ALTER TABLE prices  ADD CONSTRAINT close_adj_positive CHECK (close_adj > 0);
-- `prices.source` (migracja 926b382d1715): nazwa dostawcy wiersza. Konwencje
-- `close_adj` są niekompatybilne (yfinance koryguje o dywidendy/splity,
-- Stooq/Finnhub/Binance wpisują close_adj := close), a łańcuch fallbacku
-- rozstrzyga się per zapytanie — bez tej kolumny serii z wymieszaną
-- konwencją nie da się wykryć. Wykrywanie: asset, dla którego
-- count(*) FILTER (WHERE close_adj = close) > 0 i
-- count(*) FILTER (WHERE close_adj <> close) > 0 jednocześnie.
```

## Droga powrotu (sekcja 10 projektu)

Gdyby wróciły transakcje: `holdings` staje się projekcją z `transactions`, `portfolio_valuations` dostaje kolumnę przepływów, wraca ADR-006. Nic w tym schemacie tego nie blokuje — dlatego `valid_from` i `NUMERIC(20,8)` są od początku.
