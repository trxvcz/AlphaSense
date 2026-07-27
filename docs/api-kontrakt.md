# Kontrakt API

Prefiks `/api`. Uwierzytelnianie: `Authorization: Bearer <access>`; refresh w httpOnly cookie.
**Kwoty i ilości zawsze jako stringi dziesiętne.** Daty w formacie `YYYY-MM-DD`.

## Auth

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/auth/register` | rejestracja |
| POST | `/auth/login` | logowanie, zwraca access + ustawia cookie |
| POST | `/auth/refresh` | rotacja refresh tokenu |
| POST | `/auth/logout` | unieważnienie refresh po stronie serwera |
| GET | `/auth/google/start`, `/auth/google/callback` | OAuth PKCE |

Refresh token: httpOnly cookie `refresh_token`, `Path=/api/auth`, `SameSite=Lax`, `Secure` poza `env=dev`. Rotowany przy każdym `/auth/refresh` (stary od razu `revoked_at`). Reużycie tokena, który już ma następcę, jest sygnałem kradzieży — unieważnia **wszystkie** aktywne refresh tokeny użytkownika (401 na tej i kolejnych próbach, aż do ponownego logowania).

**OAuth Google (Authorization Code + PKCE, backend-only, ADR-005):**

- `GET /auth/google/start` → `302` na Google, `Set-Cookie: oauth_state=<jwt>; HttpOnly; SameSite=Lax; Path=/api/auth/google` (10 min). `state`/`code_verifier` (PKCE) generuje Authlib, backend je zamyka podpisane w cookie — bez sesji serwerowej (projekt jest stateless-JWT).
- `GET /auth/google/callback?code=&state=` → weryfikuje `state` z query kontra `state` z cookie `oauth_state`, wymienia `code` na token **wyłącznie z backendu** (nigdy z frontendu), pobiera profil z `userinfo_endpoint` Google. Konto dopasowane/utworzone po `email` (bez kolumny `google_id` — konta OAuth-only mają `password_hash IS NULL` i nie mogą się logować przez `/auth/login`). `200` z tą samą odpowiedzią co `/auth/login` (access w body, refresh w cookie), czyści cookie `oauth_state`.
- Błędy: brak/niezgodny `state`, brak `code`, `error` z Google, e-mail niezweryfikowany w Google, nieudana wymiana kodu → `401 unauthorized`.

## Portfele i pozycje

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET/POST | `/portfolios` | lista / utworzenie |
| GET/PATCH/DELETE | `/portfolios/{portfolio_id}` | szczegóły |
| GET/POST | `/portfolios/{portfolio_id}/holdings` | pozycje |
| PATCH/DELETE | `/holdings/{holding_id}` | edycja ilości / usunięcie |
| GET | `/portfolios/{portfolio_id}/summary` | wartość, zmiana d/d, YTD (skrót „Twoje rynki" dochodzi w kroku 29/30) |
| GET | `/portfolios/{portfolio_id}/valuations?range=1M\|3M\|1Y\|YTD\|max` | seria snapshotów |

## Struktura i rynki

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/portfolios/{portfolio_id}/allocation?by=class\|sector\|geo\|currency\|market` | alokacja |
| GET | `/portfolios/{portfolio_id}/concentration` | top5, liczba pozycji, HHI + interpretacja |
| GET | `/portfolios/{portfolio_id}/markets` | ranking rynków wg wagi + dane indeksów |
| GET | `/markets/{code}/index?range=` | seria indeksu referencyjnego |

## Ryzyko i wyniki (Faza 2)

`GET /portfolios/{portfolio_id}/risk`, `GET /portfolios/{portfolio_id}/performance?benchmark=WIG20`

## Pomocnicze

`GET /assets/search?q=`, `GET /assets/{id}`, `PATCH /assets/{id}/metadata` (override), `GET /meta/freshness`, `GET /health`

`GET /assets/search` i `GET /meta/freshness` są **publiczne** (bez `Authorization`) — `assets`/`markets`/`ingestion_runs` to słowniki globalne, nie zasoby użytkownika (żaden FK do `users`), więc nie ma tu czego chronić przez `get_owned_*`. Pierwsze publiczne trasy pod `/api` poza `/health`.

## Kształty odpowiedzi

```jsonc
// POST /auth/register  → 201
// body: { "email": "user@example.com", "password": "min. 8 znaków" }
{ "id": "uuid", "email": "user@example.com", "created_at": "2026-07-24T11:55:38.517098Z" }

// POST /auth/login  → 200, Set-Cookie: refresh_token=...; HttpOnly; SameSite=Lax; Path=/api/auth
// body: { "email": "user@example.com", "password": "..." }
{ "access_token": "<jwt>", "token_type": "bearer" }

// POST /auth/refresh  → 200, czyta refresh z cookie (nie z body), rotuje cookie
{ "access_token": "<jwt>", "token_type": "bearer" }

// POST /auth/logout  → 204, czyści cookie refresh_token po stronie serwera (idempotentne)

// POST /portfolios  → 201
// body: { "name": "Mój portfel", "type": "standard" }
{ "id": "uuid", "name": "Mój portfel", "type": "standard", "holdings_version": 0, "created_at": "2026-07-27T09:12:00.000000Z" }

// POST /portfolios/{portfolio_id}/holdings  → 201
// body: { "asset_id": "uuid", "quantity": "10", "avg_cost": "180.00", "cost_currency": "USD", "note": "opcjonalna notatka" }
// avg_cost/cost_currency opcjonalne razem (jeśli avg_cost podany, cost_currency wymagany — 422 inaczej)
// unrealized_pl liczony kursem NBP z dnia bieżącej wyceny (nie z historycznej daty zakupu — transakcji nie przechowujemy)
{
  "id": "uuid", "asset_id": "uuid", "symbol": "AAPL",
  "quantity": "10.00000000", "avg_cost": "180.00000000", "cost_currency": "USD", "note": "opcjonalna notatka",
  "value_pln": "7600.00000000", "stale": false, "as_of": "2026-07-27",
  "unrealized_pl": "400.00000000", "split_suspected": false
}
// 409, jeśli pozycja dla tego asset_id już istnieje w portfelu (UNIQUE(portfolio_id, asset_id))

// GET /portfolios/{portfolio_id}/holdings
// pozycje wycenione na "dziś" — bez ceny/kursu: value_pln=null, stale=true, wyłączona z sumy portfela (nigdy 0)
[
  {
    "id": "uuid", "asset_id": "uuid", "symbol": "CDR",
    "quantity": "10.00000000", "avg_cost": null, "cost_currency": null, "note": null,
    "value_pln": "1250.00000000", "stale": false, "as_of": "2026-07-27",
    "unrealized_pl": null, "split_suspected": false
  },
  {
    "id": "uuid", "asset_id": "uuid", "symbol": "bitcoin",
    "quantity": "0.10000000", "avg_cost": "60000.00000000", "cost_currency": "USD", "note": null,
    "value_pln": null, "stale": true, "as_of": null,
    "unrealized_pl": null, "split_suspected": false
  }
]

// PATCH /holdings/{holding_id}  → 200
// body: pola opcjonalne { quantity?, avg_cost?, cost_currency?, note? } — pominięte pole = bez zmian;
// avg_cost/cost_currency/note jawnie na null = wyczyszczone; quantity jawnie na null → 422
// (kolumna NOT NULL, "wyczyść ilość" nie ma sensu — to samo dotyczy PATCH /portfolios: name/type jawnie null → 422).
// PATCH bez żadnego pola ({}) jest no-op — nie bumpuje holdings_version/dnia zmiany składu.
// body: { "quantity": "12" }
{
  "id": "uuid", "asset_id": "uuid", "symbol": "CDR",
  "quantity": "12.00000000", "avg_cost": null, "cost_currency": null, "note": null,
  "value_pln": "1500.00000000", "stale": false, "as_of": "2026-07-27",
  "unrealized_pl": null, "split_suspected": false
}

// GET /portfolios/{portfolio_id}/summary
// bez pola "markets" (ranking rynków z indeksami referencyjnymi) — świadomie, to krok 29/30 (etap 6), poza
// zakresem etapu 5; change_1d/change_ytd mogą być null, jeśli worker jeszcze nie zapisał żadnego snapshotu
{
  "value_pln": "128450.32",
  "change_1d": { "abs": "-820.11", "pct": "-0.0063" },
  "change_ytd": { "abs": "9120.44", "pct": "0.0765" },
  "as_of": "2026-07-23",
  "stale_assets": 0
}

// GET /portfolios/{portfolio_id}/valuations?range=1M  (posortowane rosnąco po dacie; brak historii → [])
[
  { "date": "2026-06-27", "value_pln": "120000.00000000", "composition_change": false },
  { "date": "2026-07-27", "value_pln": "128450.32000000", "composition_change": true }
]

// GET /portfolios/{portfolio_id}/allocation?by=sector  (etap 6, krok 29)
// "by" wymagany (brak wartości domyślnej — 422 zamiast zgadywania wymiaru).
// approximate=true TYLKO dla by=sector/by=geo, gdy w wycenionych pozycjach jest ETF
// (sektor/geografia ETF-a to przybliżenie — klasa/waluta/rynek nie, tam zawsze false).
// weight: 4 miejsca po przecinku (ułamek, jak change_1d.pct), value_pln: 8 miejsc
// (jak wszędzie indziej w API) — suma "weight" po buckets zawsze dokładnie "1"
// (poza pustym portfelem/brakiem wycenionych pozycji: buckets: []).
// Brak atrybutu (np. sector=null) → koszyk "nieznane", pozycja nie jest pomijana.
{
  "by": "sector",
  "as_of": "2026-07-23",
  "approximate": true,
  "buckets": [
    { "key": "Technologia", "value_pln": "42010.00000000", "weight": "0.9910" },
    { "key": "nieznane",    "value_pln": "380.00000000",   "weight": "0.0090" }
  ]
}

// GET /portfolios/{portfolio_id}/concentration  (etap 6, krok 29)
// top5_share/hhi liczone po wagach POZYCJI (nie koszyków), 4 miejsca po przecinku.
// interpretation: hhi<0.15 "niska", 0.15-0.25 "średnia", >0.25 "wysoka".
// Portfel pusty / brak wycenionych pozycji → top5_share="0", count=0, hhi="0", interpretation="niska".
{ "top5_share": "0.6100", "count": 14, "hhi": "0.1900", "interpretation": "średnia" }

// GET /assets/search?q=cdr  (min. 2 znaki; brak/za krótkie q → 422, patrz „Błędy")
// szuka po symbol/name (ILIKE '%q%', case-insensitive), max 20 trafień, tylko aktywa is_active=true.
// aktywom bez sector/country zleca uzupełnienie metadanych w tle (nie blokuje odpowiedzi)
[
  { "id": "uuid", "symbol": "CDR", "name": "CD Projekt", "asset_class": "equity", "market_code": "GPW", "currency": "PLN" }
]

// GET /meta/freshness
// świeże = jest przebieg ingestii (dowolnego statusu) z dzisiaj lub wczoraj (UTC);
// rynek bez żadnego ingestion_run → stale: true, last_run_at/status: null (nie błąd)
{
  "markets": [
    { "code": "GPW", "name": "Giełda Papierów Wartościowych", "last_run_at": "2026-07-23T18:31:04.221000Z", "status": "ok", "stale": false },
    { "code": "CRYPTO", "name": "Rynek krypto (24/7)", "last_run_at": null, "status": null, "stale": true }
  ]
}
```

## Rate limiting

Limit domyślny (`RATE_LIMIT_DEFAULT_PER_MINUTE`, domyślnie 100/minutę) obowiązuje każdą trasę pod `/api`, liczony per adres IP + ścieżka. `POST /auth/register` i `POST /auth/login` mają ostrzejszy, dedykowany limit (`RATE_LIMIT_AUTH_PER_MINUTE`, domyślnie 5/minutę) — chroni przed zalewaniem rejestracjami i zgadywaniem hasła. `/auth/refresh`, `/auth/logout` i `/auth/google/*` zostają na limicie domyślnym (wymagają już poprawnego tokenu albo idą przez Google). Liczniki żyją w Redisie (nie w pamięci procesu API), więc przetrwają restart/wiele replik.

Przekroczenie limitu → `429`:

```jsonc
{ "error": { "code": "rate_limited", "message": "Przekroczono limit żądań, spróbuj ponownie później.", "details": { "limit": "5 per 1 minute" } } }
```

## Błędy

```jsonc
{ "error": { "code": "not_found", "message": "Nie znaleziono portfela", "details": null } }
```

| Kod HTTP | Kiedy |
|---|---|
| 400 / 422 | błąd walidacji |
| 401 | brak lub wygasły access token |
| 404 | zasób nie istnieje **lub należy do innego użytkownika** (konsekwentnie) |
| 409 | konflikt (pozycja dla tego aktywa już istnieje) |
| 429 | rate limit (patrz sekcja „Rate limiting" powyżej) |
| 503 | dostawca danych niedostępny, dane mogą być nieświeże |

## Zasada aktualizacji

Nowy endpoint dopisujesz **tutaj w tym samym commicie**, w którym powstaje. Ten plik jest kontraktem dla frontendu.
