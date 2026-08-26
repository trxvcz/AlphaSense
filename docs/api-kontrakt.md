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
| GET | `/portfolios/{portfolio_id}/allocation?by=class\|sector\|geo\|currency\|market&tags=` | alokacja (cache Redis, patrz „Cache" niżej); `tags` (krok 43) to opcjonalna lista nazw po przecinku (maks. 20, powyżej `422`), semantyka **OR** |
| GET | `/portfolios/{portfolio_id}/concentration` | top5, liczba pozycji, HHI + interpretacja (cache Redis) |
| GET | `/portfolios/{portfolio_id}/markets` | ranking rynków wg wagi + dane indeksów (cache Redis) |
| GET | `/markets/{code}/index?range=` | seria indeksu referencyjnego — **publiczna** trasa (bez `Authorization`), patrz sekcja „Pomocnicze" niżej. **Bez cache** (świadomie poza zakresem kroku 31 — nie ma `portfolio_id`, propozycja do rozważenia osobno w `analytics/service.py`, sekcja „Krok 31") |

## Ryzyko i wyniki (Faza 2)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/portfolios/{portfolio_id}/performance?range=1M\|3M\|1Y\|YTD\|max&benchmark=WIG20\|^GSPC` | zwrot za okres + seria indeksu łańcuchowego + opcjonalna seria porównawcza (kroki 40 i 42, cache Redis) |
| GET | `/portfolios/{portfolio_id}/risk?range=1M\|3M\|1Y\|YTD\|max&benchmark=WIG20\|^GSPC` | zmienność, Sharpe, max drawdown + underwater, beta, zwroty miesięczne (krok 41b, cache Redis) |

```jsonc
// GET /portfolios/{id}/performance?range=1M  (etap 8, krok 40)
{
  "range": "1M",
  "period_return": "0.1000",       // null, gdy nie ma ANI JEDNEGO ogniwa
  "first_date": "2026-07-13",
  "last_date": "2026-08-12",
  "links": 22,                     // z ilu ogniw policzono zwrot
  "skipped_composition_change": 1, // ogniwa zerwane przez zmianę składu
  "skipped_zero_base": 0,          // ogniwa z zerową bazą (dane wyglądają źle)
  "points": [
    { "date": "2026-07-13", "value_pln": "1000.00000000", "ret": null,       "index": "100.0000" },
    { "date": "2026-07-14", "value_pln": "1100.00000000", "ret": "0.100000", "index": "110.0000" },
    // dzień zmiany składu: wartość rośnie o dopłatę, indeks STOI, zwrotu nie znamy
    { "date": "2026-07-15", "value_pln": "1600.00000000", "ret": null,       "index": "110.0000" }
  ]
}
```

**Zwrot jest łańcuchowy, nie `V_koniec / V_start - 1`.** Snapshoty nie znają przepływów (ADR-101, CLAUDE.md #1), więc dzień dopisania pozycji podniósłby zwrot o wartość dopłaty. Ogniwo `t-1 → t` w dniu `composition_change=true` **wypada z łańcucha**, ale `V_t` zostaje bazą ogniwa następnego — kasowanie obu dni wycięłoby prawdziwy zwrot dnia po dopłacie.

**`ret: null` to nie `"0"`.** `null` znaczy „zwrotu za ten dzień nie znamy" (pierwszy punkt serii albo zerwane ogniwo), `"0"` znaczy „portfel nic nie zarobił". UI nie może tych przypadków zlewać (CLAUDE.md #3.15). Tak samo `period_return: null` dla portfela bez historii.

**Przerwa w serii łączy łańcuch.** Weekend, święto i dzień bez przebiegu workera wyglądają w tabeli tak samo — jako brak wiersza. Zrywanie przy każdej przerwie zaniżałoby zwrot bez ostrzeżenia, dlatego przerwa łączy, a `links` mówi, ile ogniw faktycznie weszło do iloczynu: „zwrot za 1Y z 40 ogniw" ma wyglądać inaczej niż ten sam zwrot z 250.

**`index` (baza 100 w pierwszym punkcie) to seria dla wykresu, nie `value_pln`.** Ta sama seria jest podstawą drawdownu w kroku 41 i porównania z benchmarkiem.

### `?benchmark=` (krok 42)

Bez parametru `benchmark` w odpowiedzi jest `null`. Z parametrem dochodzi druga seria, znormalizowana do 100 **w tym samym dniu co portfel** (pierwsza data okna), przeliczona na PLN kursem NBP.

```jsonc
// GET /portfolios/{id}/performance?range=1Y&benchmark=WIG20
{
  // … pola jak wyżej …
  "benchmark": {
    "key": "WIG20",             // o co pytał użytkownik
    "symbol": "ETFBW20TR",      // czym to faktycznie policzono
    "label": "WIG20 (przez Beta ETF WIG20TR)",
    "currency": "PLN",           // null, gdy serii nie da się policzyć
    "approximate": true,
    "note": "Liczone z ETF-a Beta WIG20TR, bo sam indeks WIG20 nie ma dostępnego źródła historii. …",
    "unavailable_reason": null, // niepuste ⇒ points puste
    "outperformance": "6.0000", // portfel − benchmark w p.p.; null, gdy serii nie ma
    "points": [
      { "date": "2025-08-12", "as_of": "2025-08-12", "index": "100.0000" },
      // `as_of` wcześniejsze niż `date` = giełda była zamknięta, wartość niesiona z poprzedniej sesji
      { "date": "2025-08-15", "as_of": "2025-08-14", "index": "101.2300" }
    ]
  }
}
```

**Dziedzina `?benchmark=` jest zamknięta** (`WIG20`, `^GSPC`) — 422 na cokolwiek innego. Otwarta dziedzina byłaby obietnicą, że każde aktywo ze słownika ma historię nadającą się na benchmark; nie ma (samo `WIG20` w `prices` ma trzy notowania).

**`key` ≠ `symbol` dla GPW.** Użytkownik prosi o WIG20, liczy to ETF `ETFBW20TR` — indeks WIG20 nie ma dziś darmowego źródła historii (decyzja 8 planu etapu 8: Stooq oddaje stronę anty-bot, yfinance jeden punkt). ETF śledzi WIG20 **Total Return**, dochodzi błąd odwzorowania i opłata ok. 0,5% rocznie, stąd `approximate: true` i `note` — UI ma to pokazać, nie ukryć (CLAUDE.md #3.15).

**`outperformance` liczy backend, nie front.** Obie serie mają bazę 100, więc różnica ostatnich punktów **jest** różnicą stóp zwrotu w punktach procentowych. Liczona na `Decimal` po stronie API i oddana jako `string`, bo trafia do użytkownika (CLAUDE.md §8) — front ma ją sformatować, nie odtworzyć. `null`, gdy serii benchmarku nie ma albo ostatnie punkty obu serii nie są z tego samego dnia.

**Benchmark przeliczany na PLN** kursem NBP z reguły `max(date) <= D` (decyzja 4 planu etapu 8). Kurs jest częścią realnego wyniku inwestora — porównanie portfela w PLN z indeksem w USD mieszałoby dwie różne miary. Brak kursu w dniu startu ⇒ `unavailable_reason`, nie cichy mnożnik 1.

**Wyrównanie kalendarzy.** Snapshoty portfela i sesje giełdy nie leżą na tych samych datach. Dla każdej daty portfela benchmark bierze ostatnie notowanie nie późniejsze niż ona (`as_of`) — nie interpoluje i nie przesuwa dat portfela. Brak notowania w dniu startu **lub wcześniej** ⇒ `unavailable_reason`: bez wspólnego punktu odniesienia obie linie startowałyby w różnych miejscach osi X.

### `/risk` (krok 41b)

```jsonc
// GET /portfolios/{id}/risk?range=1Y&benchmark=^GSPC
{
  "range": "1Y",
  "first_date": "2025-08-25",
  "last_date": "2026-08-25",
  "observations": 261,          // liczba ogniw, z których liczono
  "min_observations": 20,       // próg, poniżej którego metryki są `null`
  "volatility": "0.2958",       // annualizowana (σ·√252); null ⇒ patrz reason
  "volatility_unavailable_reason": null,
  "sharpe": "-0.895185",        // annualizowany, na nadwyżce ponad stopę NBP
  "sharpe_unavailable_reason": null,
  "risk_free_label": "Stopa referencyjna NBP (historyczna, źródło: NBP)",
  "max_drawdown": {
    "value": "-0.3964",         // UJEMNE — znak niesie kierunek
    "peak_date": "2025-10-06",
    "trough_date": "2026-02-05",
    "recovered_at": null        // null = jeszcze nieodrobione
  },
  "underwater": [               // dystans do biegnącego szczytu, per dzień
    { "date": "2025-08-25", "value": "0.0000" },
    { "date": "2025-08-26", "value": "-0.0123" }
  ],
  "monthly_returns": [          // miesiące BEZ ogniw po prostu nie występują
    { "year": 2025, "month": 9, "ret": "0.0288", "links": 21 }
  ],
  "beta": {                     // null, gdy nie podano `?benchmark=`
    "key": "WIG20",
    "symbol": "ETFBW20TR",
    "label": "WIG20 (przez Beta ETF WIG20TR)",
    "approximate": true,
    "value": "0.283949",
    "observations": 261,
    "unavailable_reason": null
  }
}
```

**Wszystko liczone z tej samej serii co `/performance`** — ogniwa i indeks łańcuchowy ze snapshotów, nigdy `value_pln` (ADR-101). Wpłata podnosi wartość portfela bez żadnego zysku, więc drawdown na `value_pln` pokazałby dopłatę jako wyjście z obsunięcia, a zmienność liczyłaby ją jako zmienność rynku.

**Każda metryka ma WŁASNY `*_unavailable_reason`.** Przy tej samej serii zmienność bywa policzalna, a Sharpe nie — bo Sharpe dodatkowo wymaga stopy referencyjnej NBP z `nbp_reference_rates` (krok 41a). Jeden wspólny komunikat kłamałby o jednym z nich. Teksty są po polsku i gotowe do wyświetlenia (CLAUDE.md #3.15).

**Sharpe używa stopy ZMIENNEJ W CZASIE.** Dla każdego ogniwa brana jest stopa referencyjna obowiązująca w jego dniu (`max(effective_from) <= D`), podzielona przez 252. Stała stopa na wieloletniej serii dałaby inny wynik — stopa szła w tym okresie od 0,10% do 6,75%. Dni, dla których stopy nie znamy, **wypadają w parze ze swoim zwrotem**; zostawienie zwrotu bez stopy znaczyłoby ciche przyjęcie rf = 0 dla tego dnia. Gdy po odrzuceniu zostaje mniej niż `min_observations` par, `sharpe` to `null` z powodem, nigdy liczba.

**`min_observations` = 20.** Poniżej tego progu zmienność, Sharpe i beta są szumem, nie oszacowaniem, więc API zwraca `null`. **Drawdown progu NIE ma** — jedno obsunięcie jest faktem niezależnie od długości serii, w odróżnieniu od oszacowania rozkładu.

**`max_drawdown.value` jest ujemne**, a `0` znaczy „portfel nigdy nie spadł poniżej szczytu" (prawdziwa odpowiedź). Brak historii to `null` całego obiektu — to co innego niż zero.

**`monthly_returns` składa ogniwa (`Π(1+r)−1`), nie dzieli indeksu z krańców miesiąca.** W miesiącu ze zmianą składu indeks stoi na zerwanym ogniwie, więc iloraz krańców przypisałby miesiącowi zwrot za dni, których nie znamy. `links` mówi, z ilu dni miesiąc powstał — miesiąc z 3 dni i z 20 wygląda na heatmapie identycznie.

**`beta` wymaga `?benchmark=`**; bez niego jest `null` i **nie jest to brak danych**. Ogniwa portfela i zwroty benchmarku są parowane **po datach** (`previous_date → date`), nie zestawiane obok siebie: ogniwa portfela bywają pomijane (zmiana składu), więc naiwne zestawienie przesunęłoby serie i dało betę wyglądającą normalnie i nieprawdziwą.

## Newsy (Faza 3)

`GET /portfolios/{portfolio_id}/news?limit=&with_sentiment_only=`

Feed jest **zawsze w kontekście portfela** — nie ma trasy „wszystkie newsy". Powód produktowy: ekran odpowiada na pytanie „co się dzieje z moimi pozycjami", a nie „co słychać w gospodarce" (CLAUDE.md §1). Efekt uboczny jest bezpieczeństwowy: każda trasa newsowa przechodzi przez `get_owned_portfolio`.

```jsonc
// GET /portfolios/{id}/news → 200
{
  "items": [
    {
      "id": "…",
      "title": "WIG20 z nowym rekordem zamknięcia",
      "url": "https://www.bankier.pl/…",
      "source": "bankier.pl",
      "published_at": "2026-08-10T18:12:00Z",
      "summary": "…",
      "sentiment": null,          // string | null — patrz niżej
      "sentiment_source": null,
      "assets": [                 // wyłącznie aktywa Z TEGO portfela
        { "symbol": "WIG20", "match_confidence": "heuristic" },
        { "symbol": "AAPL",  "match_confidence": "source" }
      ]
    }
  ],
  "assets_covered": 3,
  "assets_without_news": ["CDR", "PKN"]
}
```

`sentiment` jest `null` dla wszystkich źródeł polskich — żaden feed RSS go nie publikuje, a darmowe źródła, które go liczą, pokrywają w praktyce wyłącznie spółki US. To **stan normalny**, nie brak do uzupełnienia; UI ma to oznaczyć (CLAUDE.md #3.15). `sentiment_source` odróżnia „dostawca ocenił neutralnie" (`sentiment: "0"`) od „nikt nie oceniał" (`sentiment: null`). Jedynym dostawcą oceny jest dziś Alpha Vantage (`NEWS_SENTIMENT`); Finnhub jej na darmowym planie nie oddaje (`/news-sentiment` → 403).

`assets[].match_confidence` mówi, **skąd wzięło się powiązanie** newsu z aktywem:

| wartość | znaczenie | źródło |
|---|---|---|
| `source` | dostawca pytany o symbol sam wskazał to powiązanie — **fakt** | Finnhub `/company-news`, Alpha Vantage `ticker_sentiment` (trafność ≥ 0,9) |
| `heuristic` | dopasowanie polskiego tekstu po naszej stronie — **przybliżenie** | `app/modules/news/matching.py` |

UI ma obowiązek pokazać tę różnicę (CLAUDE.md #3.15). Pole jest **per aktywo, nie per news**, i to jest istotne: jedna depesza bywa pewnie powiązana z `AAPL` (bo Finnhub tak powiedział) i jednocześnie zgadnięta dla złota (bo w tekście padło słowo „złoto"). Jedna zbiorcza flaga musiałaby wybrać jedną z tych dwóch prawd i drugą przekłamać.

Lista `assets` jest **zawężona do aktywów pytającego portfela**. To wymóg izolacji, nie optymalizacja: wiersz `news` jest współdzielony przez wszystkich użytkowników (newsy nie mają FK do `users`), więc nieprzefiltrowana lista powiedziałaby użytkownikowi, co trzymają inni (CLAUDE.md #3.2).

`assets_without_news` wymienia pozycje portfela, dla których nie ma **żadnego** powiązanego newsu. Pole istnieje, bo pusty feed ma dwie różne przyczyny — nic się nie ukazało albo nie umiemy rozpoznać spółki w tekście (dopasowanie jest heurystyką na polskim tekście, patrz `app/modules/news/matching.py`) — a użytkownik widzi w obu przypadkach to samo.

## Dywidendy (Faza 3, krok 47)

`GET /portfolios/{portfolio_id}/dividends?horizon_days=`

Kalendarz jest **zawsze w kontekście portfela**, tak jak feed newsów: odpowiada na pytanie „które z moich pozycji mają najbliżej do ex-daty i ile z tego orientacyjnie wyjdzie". `horizon_days` ∈ [1, 365], domyślnie 90 — dalej niż rok w przód żaden darmowy dostawca nie sięga zapowiedziami.

```jsonc
// GET /portfolios/{id}/dividends → 200
{
  "items": [
    {
      "symbol": "AAPL",
      "market_code": "US",
      "ex_date": "2026-11-09",        // jedyna data zawsze obecna
      "record_date": "2026-11-09",
      "pay_date": "2026-11-12",       // null = jeszcze nieogłoszona
      "declaration_date": "2026-10-29",
      "amount_per_share": "0.27000000",  // string, BRUTTO, waluta notowania
      "currency": "USD",
      "quantity": "10.00000000",
      "estimated_gross": "2.70000000",   // amount_per_share × quantity
      "source": "alphavantage_dividends",
      "fetched_at": "2026-08-23T05:15:00Z"
    }
  ],
  "horizon_days": 90,
  "assets_covered": 1,
  "assets_without_coverage": ["CDR", "PKN"],
  "uncovered_markets": ["GPW"]
}
```

**Okno zaczyna się dziś.** Zdarzenie z wczorajszą ex-datą jest już nie do złapania, a pokazane w kalendarzu „nadchodzących" sugerowałoby, że da się z nim jeszcze coś zrobić. Historia wypłat to inny zakres (Etap 21).

**Kwoty są brutto, w walucie notowania i bez przeliczenia na PLN.** Kurs właściwy dla wypłaty to kurs z dnia poprzedzającego wypłatę, czyli z przyszłości — liczba w PLN pokazana dziś byłaby prognozą udającą wycenę (CLAUDE.md #3.15). Podatek u źródła i rozliczenie należą do Etapu 21 (CLAUDE.md §22). `estimated_gross` liczy się z **dzisiejszej** wielkości pozycji; dokupienie lub sprzedaż przed ex-datą zmienia wynik.

**`assets_without_coverage` i `uncovered_markets` są najważniejszą częścią tej odpowiedzi.** Dostawcą jest dziś Alpha Vantage (`DIVIDENDS`) — Finnhub `/stock/dividend` zwraca na darmowym planie `403` (sprawdzone 2026-08-23), mimo że plan kroku 47 zakładał właśnie jego. Alpha Vantage **nie pokrywa GPW**: dla `PKN.WAR` oddaje `data: []`, czyli odpowiedź nie do odróżnienia od „spółka nie płaci". Dlatego pokrycie rozstrzyga **mapowanie `asset_source_map` (provider `alphavantage_dividends`)**, a nie obecność zdarzeń w bazie: aktywo bez mapowania jest raportowane jako nieobjęte, a nie jako „bez dywidend". Rynek trafia do `uncovered_markets` dopiero wtedy, gdy żadne aktywo portfela z tego rynku nie ma pokrycia.

## Świece (Faza 2, krok 45)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/assets/{asset_id}/candles?range=1M\|3M\|1Y\|YTD\|max` | świece OHLC instrumentu; `range` domyślnie `1Y`. **Publiczna** (notowania to słownik globalny) |

```json
{
  "symbol": "AAPL", "name": "Apple Inc.", "currency": "USD", "range": "1M", "skipped": 1,
  "candles": [
    {"date": "2026-08-06", "open": "314.06913777", "high": "316.01746969",
     "low": "308.96355556", "close": "312.14080811", "volume": 46139900}
  ]
}
```

**Wszystkie cztery ceny są skorygowane** o splity i dywidendy — współczynnikiem `close_adj / close` z tego samego dnia, tym samym dla całej świecy. `prices` trzyma surowe OHLC i skorygowany wyłącznie `close_adj`, więc narysowanie świec wprost z kolumn złamałoby CLAUDE.md #4: knoty i korpusy sprzed splitu wisiałyby kilka razy wyżej niż linia zamknięcia znana z pozostałych wykresów. `close` bierzemy wprost z `close_adj` (bez mnożenia i dzielenia), żeby zgadzał się co do grosza z wyceną pozycji. `volume` przechodzi **bez** skalowania — to sztuki, nie cena, stąd liczba, a nie string.

**`skipped` to liczba sesji, których nie da się pokazać**: brak kompletu OHLC albo `close <= 0`, czyli brak współczynnika korekty. Jest w odpowiedzi, bo wykres z dziurą wygląda dokładnie jak wykres kompletny (CLAUDE.md #3.15) — UI musi mieć czym to oznaczyć.

**Indeks rynku jedzie tą samą trasą.** Indeks referencyjny jest zwykłym aktywem (`markets.index_asset_id`, ADR-102), a `GET /portfolios/{id}/markets` oddaje jego `asset_id` — osobne `/markets/{code}/candles` byłoby endpointem bez konsumenta.

**404** dla nieznanego `asset_id`; aktywo wygaszone (`is_active = false`) świec **nie** traci — historia notowań pozostaje prawdziwa, wygaszenie mówi tylko „nie pytamy o nowe ceny". Brak notowań w oknie to `200` z pustą listą, nie 404: pojęcie serii istnieje, danych jeszcze nie ma.

## Tagi i listy obserwowanych (Faza 2, krok 43)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET/POST | `/tags` | tagi użytkownika (alfabetycznie, z `asset_count`) / utworzenie |
| PATCH/DELETE | `/tags/{tag_id}` | zmiana nazwy lub koloru / usunięcie |
| GET | `/tags/{tag_id}/assets` | aktywa oznaczone tagiem |
| PUT/DELETE | `/tags/{tag_id}/assets/{asset_id}` | powiązanie tagu z aktywem (idempotentne, 204) |
| GET/POST | `/watchlists` | listy obserwowanych (z `item_count`) / utworzenie |
| PATCH/DELETE | `/watchlists/{watchlist_id}` | zmiana nazwy / usunięcie |
| GET | `/watchlists/{watchlist_id}/items` | pozycje listy |
| PUT/DELETE | `/watchlists/{watchlist_id}/items/{asset_id}` | dodanie (z `note`) / usunięcie (idempotentne, 204) |

**Chronionym zasobem jest tag albo lista, nigdy aktywo.** `assets` to słownik globalny — własność niesie `tags.user_id` / `watchlists.user_id`. Stąd kształt `/tags/{tag_id}/assets/{asset_id}`, a nie odwrotnie: identyfikator do zweryfikowania jest pierwszy w ścieżce. Cudzy tag/lista → **404**, nigdy 403.

**Nazwa jest unikalna per użytkownik.** Duplikat → `409` z komunikatem po polsku (`UNIQUE` w bazie zostaje jako ostatnia linia obrony). Ta sama nazwa u dwóch różnych użytkowników jest poprawna — inaczej pierwsza osoba, która założy „dywidendowe", zablokowałaby tę nazwę wszystkim.

**`PUT` zamiast `POST` przy wiązaniu**, bo operacja jest idempotentna: powtórne otagowanie nie jest błędem, a powtórne dodanie do watchlisty aktualizuje `note`. `DELETE` zwraca `204` także wtedy, gdy powiązania nie było — stan końcowy jest ten sam, a `404` kazałoby klientowi rozróżniać przypadki, które go nie obchodzą. Nieistniejące `asset_id` → `404`.

**`PATCH /tags/{tag_id}` rozróżnia „nie zmieniaj" od „skasuj".** Pominięcie `color` zostawia kolor, jawny `"color": null` go kasuje. Kolor jest opcjonalny i **nigdy nie jest jedynym nośnikiem informacji** (CLAUDE.md §21) — UI pokazuje nazwę tagu obok koloru.

**Watchlista to nie drugi portfel** (CLAUDE.md #3.11). `WatchlistItemOut` świadomie nie ma `value_pln`, `quantity` ani zwrotu — obserwowanie nie jest posiadaniem, a dołożenie tam wyceny byłoby cichym rozszerzeniem zakresu v2.

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
allocation:{portfolio_id}:{by}:tags=[{skrót nazw}:{tags_version}]:{holdings_version}:{eod_marker}
concentration:{portfolio_id}:{holdings_version}:{eod_marker}
markets:{portfolio_id}:{holdings_version}:{eod_marker}
performance:{portfolio_id}:{holdings_version}:{valuations_marker}:{range}:{benchmark}:{benchmark_marker}
```

`holdings_version` to znacznik ostatniej zmiany składu portfela (`Portfolio.holdings_version`, bumpowany przy każdym CRUD `holdings`). `eod_marker` to `MAX(prices.date)` wśród aktywów **faktycznie trzymanych** w tym portfelu (`"none"`, jeśli portfel jest pusty albo żadne z jego aktywów nie ma jeszcze notowania) — zmienia się dopiero, gdy dla tego portfela realnie przyjdą nowe dane EOD, nie o północy jak `today()`. TTL: 6 godzin (Redis nie puchnie starymi kluczami; dane EOD i tak nie zmieniają się śróddziennie).

Segment `tags=` (krok 43) jest w kluczu **zawsze**, także bez filtra — wtedy pusty (`tags=`). Gdyby pojawiał się tylko przy filtrze, zapytanie z `?tags=` trafiałoby w klucz zapytania bez filtra i oddawało nieprzefiltrowany wynik. Sentynel „bez filtra" musi być **nieosiągalny jako nazwa tagu**: pusty string jest bezpieczny (`ck_tags_name_not_blank`), a wcześniejszy `-` nie był — `?tags=-` zapisywał pustą alokację pod kluczem bez filtra i przez cały TTL widok struktury pokazywał pusty portfel.

Nazwy idą do klucza przez **skrót** (SHA-256, 16 znaków) po posortowaniu i odduplikowaniu: `?tags=a,b` i `?tags=b,a,a` to to samo pytanie i mają dzielić wpis, a surowe nazwy dawałyby klucz o długości zależnej od wejścia użytkownika. Filtr przyjmuje najwyżej **20 nazw** (powyżej: `422`, bo ciche obcięcie oddawałoby wynik innego pytania niż zadane) i pomija nazwy dłuższe niż 60 znaków — takiego tagu nie da się założyć, więc nic by nie dopasował.

`tags_version` = `MAX(asset_tags.created_at)` + `COUNT(*)` powiązań tego użytkownika. Bez niego przepięcie tagu w ogóle nie zmieniałoby klucza (`holdings_version` bumpuje tylko CRUD `holdings`, `eod_marker` to `MAX(prices.date)`), więc po odpięciu spółki od tagu przez 6 h wracałyby wagi policzone ze starym składem. Sam `MAX` nie wystarczy — usunięcie powiązania nie rusza maksimum, ta sama pułapka co przy `valuations_marker` niżej.

`GET /performance` (krok 40) używa **innego markera**: `valuations_marker` = `MAX(date)` i `COUNT(*)` w `portfolio_valuations` tego portfela (`"none"` przy braku historii). Sam `MAX(date)` by tu nie wystarczył — inaczej niż ceny, snapshoty przybywają też **wstecz** (`seed-history` z kroku zerowego etapu 8 dopisuje pełne lata historii, nie ruszając maksimum), a wtedy klucz oparty na samym maksimum dałby trafienie w cache ze zwrotem policzonym z krótszej serii.

`benchmark_marker` (krok 42) jest **osobny** od `valuations_marker`: notowania benchmarku przychodzą z ingestii rynkowej, a snapshoty portfela z joba wyceny. Portfel bez ruchu i świeże notowanie `^GSPC` to sytuacja codzienna — na wspólnym markerze linia benchmarku stałaby do wygaśnięcia TTL.

Marker składa się z **trzech** segmentów, bo każdy łapie inną zmianę: `MAX(prices.date)` (nowe notowanie), `COUNT(*)` notowań (historia dopisana **wstecz** przez `make backfill` — ponad tysiąc sesji `ETFBW20TR.WA` bez ruszania maksimum, dokładnie ten sam problem co przy `valuations_marker`) oraz `MAX(fx_rates.date)` waluty benchmarku, gdy nie jest nią PLN (NBP publikuje ok. 12:00, notowania `^GSPC` przychodzą wieczorem, więc świeże notowanie potrafi przez chwilę wisieć na wczorajszym kursie). Nadpisanie istniejącego wiersza przy niezmienionej ich liczbie marker świadomie pomija — na to jest TTL, ten sam kompromis co w kroku 31.

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
