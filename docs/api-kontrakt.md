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

## Portfele i pozycje

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET/POST | `/portfolios` | lista / utworzenie |
| GET/PATCH/DELETE | `/portfolios/{id}` | szczegóły |
| GET/POST | `/portfolios/{id}/holdings` | pozycje |
| PATCH/DELETE | `/holdings/{id}` | edycja ilości / usunięcie |
| GET | `/portfolios/{id}/summary` | wartość, zmiana d/d, YTD, skrót „Twoje rynki" |
| GET | `/portfolios/{id}/valuations?range=1M\|3M\|1Y\|YTD\|max` | seria snapshotów |

## Struktura i rynki

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/portfolios/{id}/allocation?by=class\|sector\|geo\|currency\|market` | alokacja |
| GET | `/portfolios/{id}/concentration` | top5, liczba pozycji, HHI + interpretacja |
| GET | `/portfolios/{id}/markets` | ranking rynków wg wagi + dane indeksów |
| GET | `/markets/{code}/index?range=` | seria indeksu referencyjnego |

## Ryzyko i wyniki (Faza 2)

`GET /portfolios/{id}/risk`, `GET /portfolios/{id}/performance?benchmark=WIG20`

## Pomocnicze

`GET /assets/search?q=`, `GET /assets/{id}`, `PATCH /assets/{id}/metadata` (override), `GET /meta/freshness`, `GET /health`

## Kształty odpowiedzi

```jsonc
// GET /portfolios/{id}/summary
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

// GET /portfolios/{id}/allocation?by=sector
{
  "by": "sector",
  "as_of": "2026-07-23",
  "approximate": true,          // gdy w portfelu są ETF-y
  "buckets": [
    { "key": "Technologia", "value_pln": "42010.00", "weight": "0.327" },
    { "key": "nieznane",    "value_pln": "1200.00",  "weight": "0.009" }
  ]
}

// GET /portfolios/{id}/concentration
{ "top5_share": "0.61", "count": 14, "hhi": "0.19", "interpretation": "średnia" }
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
| 429 | rate limit |
| 503 | dostawca danych niedostępny, dane mogą być nieświeże |

## Zasada aktualizacji

Nowy endpoint dopisujesz **tutaj w tym samym commicie**, w którym powstaje. Ten plik jest kontraktem dla frontendu.
