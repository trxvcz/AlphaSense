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
| GET | `/portfolios/{portfolio_id}/summary` | wartość, zmiana d/d, YTD, skrót „Twoje rynki" |
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

// GET /portfolios/{portfolio_id}/summary
{
  "value_pln": "128450.32",
  "change_1d": { "abs": "-820.11", "pct": "-0.0063" },
  "change_ytd": { "abs": "9120.44", "pct": "0.0765" },
  "as_of": "2026-07-23",
  "stale_assets": 0,
  "markets": [
    { "code": "GPW", "weight": "0.41", "index": { "symbol": "WIG20", "value": "2451.20", "change_1d_pct": "0.0042" } }
  ]
}

// GET /portfolios/{portfolio_id}/allocation?by=sector
{
  "by": "sector",
  "as_of": "2026-07-23",
  "approximate": true,          // gdy w portfelu są ETF-y
  "buckets": [
    { "key": "Technologia", "value_pln": "42010.00", "weight": "0.327" },
    { "key": "nieznane",    "value_pln": "1200.00",  "weight": "0.009" }
  ]
}

// GET /portfolios/{portfolio_id}/concentration
{ "top5_share": "0.61", "count": 14, "hhi": "0.19", "interpretation": "średnia" }

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
