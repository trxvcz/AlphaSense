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
| GET | `/portfolios/{portfolio_id}/allocation?by=class\|sector\|geo\|currency\|market` | alokacja (cache Redis, patrz „Cache" niżej) |
| GET | `/portfolios/{portfolio_id}/concentration` | top5, liczba pozycji, HHI + interpretacja (cache Redis) |
| GET | `/portfolios/{portfolio_id}/markets` | ranking rynków wg wagi + dane indeksów (cache Redis) |
| GET | `/markets/{code}/index?range=` | seria indeksu referencyjnego — **publiczna** trasa (bez `Authorization`), patrz sekcja „Pomocnicze" niżej. **Bez cache** (świadomie poza zakresem kroku 31 — nie ma `portfolio_id`, propozycja do rozważenia osobno w `analytics/service.py`, sekcja „Krok 31") |

## Ryzyko i wyniki (Faza 2)

`GET /portfolios/{portfolio_id}/risk`, `GET /portfolios/{portfolio_id}/performance?benchmark=WIG20`

## Pomocnicze

`GET /assets/search?q=`, `GET /assets/{id}`, `PATCH /assets/{id}/metadata` (override), `GET /meta/freshness`, `GET /health`

`GET /assets/search`, `GET /meta/freshness` i `GET /markets/{code}/index` są **publiczne** (bez `Authorization`) — `assets`/`markets`/`ingestion_runs`/`prices` to słowniki/dane globalne, nie zasoby użytkownika (żaden FK do `users`), więc nie ma tu czego chronić przez `get_owned_*`. Pierwsze publiczne trasy pod `/api` poza `/health`.

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
// price_change_1d — zmiana CENY instrumentu d/d (close_adj dziś vs poprzednie notowanie), NIE zmiana value_pln
// portfela ani unrealized_pl (ten liczy się względem avg_cost, nie względem wczoraj); null, gdy jest mniej niż
// dwa notowania w historii (świeżo dodane aktywo) — przygotowanie pod krok 32 ("top ruchy dnia" na dashboardzie)
{
  "id": "uuid", "asset_id": "uuid", "symbol": "AAPL",
  "quantity": "10.00000000", "avg_cost": "180.00000000", "cost_currency": "USD", "note": "opcjonalna notatka",
  "value_pln": "7600.00000000", "stale": false, "as_of": "2026-07-27",
  "unrealized_pl": "400.00000000", "split_suspected": false,
  "price_change_1d": { "abs": "3.50000000", "pct": "0.0185" }
}
// 409, jeśli pozycja dla tego asset_id już istnieje w portfelu (UNIQUE(portfolio_id, asset_id))

// GET /portfolios/{portfolio_id}/holdings
// pozycje wycenione na "dziś" — bez ceny/kursu: value_pln=null, stale=true, wyłączona z sumy portfela (nigdy 0)
[
  {
    "id": "uuid", "asset_id": "uuid", "symbol": "CDR",
    "quantity": "10.00000000", "avg_cost": null, "cost_currency": null, "note": null,
    "value_pln": "1250.00000000", "stale": false, "as_of": "2026-07-27",
    "unrealized_pl": null, "split_suspected": false,
    "price_change_1d": { "abs": "-2.50000000", "pct": "-0.0196" }
  },
  {
    "id": "uuid", "asset_id": "uuid", "symbol": "bitcoin",
    "quantity": "0.10000000", "avg_cost": "60000.00000000", "cost_currency": "USD", "note": null,
    "value_pln": null, "stale": true, "as_of": null,
    "unrealized_pl": null, "split_suspected": false,
    "price_change_1d": null
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
  "unrealized_pl": null, "split_suspected": false,
  "price_change_1d": { "abs": "-2.50000000", "pct": "-0.0196" }
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

// GET /portfolios/{portfolio_id}/markets  (etap 6, krok 30, ADR-102)
// Ranking rynków wg wagi w wartości wycenionego portfela, malejąco po "weight" (4 miejsca).
// Grupowanie po asset.market_code (kolumna NOT NULL — nie ma tu koszyka "nieznane").
// "index" jest null, gdy rynek nie ma index_asset_id w słowniku markets, ALBO gdy ma go,
// ale w "prices" nie ma jeszcze żadnego notowania (worker EOD jeszcze nie zaciągnął danych)
// — oba przypadki to "brak danych, nie błąd", nie 200 z pustym wykresem.
// change_1d liczone wprost z dwóch najnowszych wierszy "prices" (nie ze snapshotów portfela) —
// null, gdy jest tylko jedno notowanie w historii. series_30d: do 30 OSTATNICH DOSTĘPNYCH
// notowań (nie 30 dni kalendarzowych), rosnąco po dacie. Portfel pusty/bez wycenionych pozycji → [].
[
  {
    "market_code": "GPW",
    "market_name": "Giełda Papierów Wartościowych",
    "weight": "0.6200",
    "index": {
      "asset_id": "uuid",
      "symbol": "WIG20",
      "value": "2100.00000000",
      "change_1d": { "abs": "100.00000000", "pct": "0.0500" },
      "as_of": "2026-07-27",
      "series_30d": [
        { "date": "2026-06-27", "close_adj": "2000.00000000" },
        { "date": "2026-07-27", "close_adj": "2100.00000000" }
      ]
    }
  },
  { "market_code": "CRYPTO", "market_name": "Rynek krypto (24/7)", "weight": "0.3800", "index": null }
]

// GET /markets/{code}/index?range=1M|3M|1Y|YTD|max  (etap 6, krok 30, ADR-102)
// Trasa PUBLICZNA (bez Authorization) — market_code nie jest zasobem użytkownika, patrz sekcja
// „Pomocnicze". Seria close_adj rosnąco po dacie, ten sam kształt zakresu co GET /valuations.
// 404, jeśli {code} nie istnieje w słowniku markets LUB istnieje, ale nie ma index_asset_id
// (pojęcie indeksu tego rynku po prostu nie istnieje — nie 200 z pustą listą).
[
  { "date": "2026-06-27", "close_adj": "2000.00000000" },
  { "date": "2026-07-27", "close_adj": "2100.00000000" }
]

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

// GET /health  (publiczne, bez `Authorization`; poza limitem domyślnym — patrz „Rate limiting")
// ZAWSZE 200, także gdy zależność leży: stan czyta się z ciała, nie z kodu HTTP.
// `status: "ok"` tylko gdy oba komponenty odpowiadają; inaczej "degraded".
// Padnięty Redis to nadal działająca aplikacja (CLAUDE.md #3.7) — healthcheck
// kontenera patrzy na pole `db`, nie na `status` (docker-compose.prod.yml).
// Odpowiedź nie niesie żadnych szczegółów awarii (host, użytkownik, wyjątek) —
// trasa jest publiczna; szczegóły idą do logów i do Sentry.
{ "status": "ok", "db": "up", "redis": "up", "version": "0.1.0" }
```

## Cache

`GET /allocation`, `GET /concentration` i `GET /markets` (plan krok 31, CLAUDE.md #3.7) są owinięte cache'em Redis w `analytics/service.py` — klucz wersjonowany, brak inwalidacji:

```
allocation:{portfolio_id}:{by}:{holdings_version}:{eod_marker}
concentration:{portfolio_id}:{holdings_version}:{eod_marker}
markets:{portfolio_id}:{holdings_version}:{eod_marker}
```

`holdings_version` to znacznik ostatniej zmiany składu portfela (`Portfolio.holdings_version`, bumpowany przy każdym CRUD `holdings`). `eod_marker` to `MAX(prices.date)` wśród aktywów **faktycznie trzymanych** w tym portfelu (`"none"`, jeśli portfel jest pusty albo żadne z jego aktywów nie ma jeszcze notowania) — zmienia się dopiero, gdy dla tego portfela realnie przyjdą nowe dane EOD, nie o północy jak `today()`. TTL: 6 godzin (Redis nie puchnie starymi kluczami; dane EOD i tak nie zmieniają się śróddziennie).

Redis można wyczyścić w każdej chwili — awaria/brak Redisa nie zwraca błędu, endpoint liczy wynik na żywo (wolniej, nie: `500`).

## Rate limiting

Limit domyślny (`RATE_LIMIT_DEFAULT_PER_MINUTE`, domyślnie 100/minutę) obowiązuje każdą trasę pod `/api`, liczony per adres IP + ścieżka, w oknie stałym (pełna minuta zegarowa). `POST /auth/register` i `POST /auth/login` mają ostrzejszy, dedykowany limit (`RATE_LIMIT_AUTH_PER_MINUTE`, domyślnie 5/minutę) w oknie przesuwnym — chroni przed zalewaniem rejestracjami i zgadywaniem hasła. `/auth/refresh`, `/auth/logout` i `/auth/google/*` zostają na limicie domyślnym (wymagają już poprawnego tokenu albo idą przez Google). Liczniki żyją w Redisie (nie w pamięci procesu API), więc przetrwają restart/wiele replik.

`GET /health` jest **wyłączone z limitu domyślnego** (`DEFAULT_LIMIT_EXEMPT_PATHS` w `core/rate_limit.py`): healthcheck kontenera odpytuje je co kilkanaście sekund z jednego adresu, więc pod wspólnym licznikiem `429` wyglądałoby dla Dockera jak awaria API i restartowałoby zdrowy kontener.

Przy niedostępnym Redisie zachowanie obu warstw jest **różne i celowo asymetryczne**: limit domyślny przepuszcza ruch (awaria cache'a nie może kłaść całego API, CLAUDE.md #3.7), limit `/auth/register`/`/auth/login` zwraca błąd (przepuszczenie otwierałoby drogę do zgadywania haseł).

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
