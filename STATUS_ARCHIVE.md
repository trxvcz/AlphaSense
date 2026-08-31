# STATUS ARCHIVE

Zarchiwizowane sekcje z poprzednich etapów (Faza 1).

## Krok 33 — widoki struktury (zrobiony 2026-07-28)

Trasa `/portfolios/[id]/struktura` (Server Component → `PortfolioStructure`, Client) plus `/struktura` z nawigacji głównej, która sama wybiera portfel: przy jednym `router.replace` prosto na widok, przy kilku lista do wyboru, przy zerze stan pusty z CTA „Utwórz portfel". Nawigacja nie miała skąd znać portfela, a struktura zawsze dotyczy konkretnego — stąd ten ekran pośredni zamiast martwego linku.

Jeden ekran z przełącznikiem wymiaru (klasa / sektor / geografia / waluta), nie cztery trasy: to jedno pytanie w czterech ujęciach, a na 375 px cztery pozycje w nawigacji nie mają gdzie się zmieścić. Forma wykresu zależy od wymiaru — **klasa → donut**, **waluta → treemapa**, **sektor i geografia → poziome słupki** (długie nazwy w rodzaju „Ameryka Północna" nie mieszczą się na kole, a koszyków bywa kilkanaście). Uzasadnienia w docstringach komponentów.

Nowe pliki: `lib/analytics.ts` (typy + `getAllocation`/`getConcentration`), `lib/chartPalette.ts`, `lib/allocationLabels.ts`, `lib/useIsDarkTheme.ts`, `components/charts/EChart.tsx`, `AllocationDonut/Treemap/Bars.tsx`, `components/structure/{PortfolioStructure,AllocationTable,ConcentrationCard}.tsx`, `app/struktura/{layout,page}.tsx`, `app/portfolios/[id]/struktura/page.tsx`. Zmienione: `lib/queryKeys.ts` (+`allocation`/`concentration`), `lib/money.ts` (+`pctAxis`), `navItems.ts` (komentarz), `PortfolioDashboard.tsx` (link do struktury), `ValueChart.tsx` (hook motywu wyciągnięty do `lib/useIsDarkTheme.ts`).

**Paleta wykresów jest policzona, nie dobrana na oko.** `lib/chartPalette.ts` używa palety kategorialnej ze skilla `dataviz`, zweryfikowanej jego walidatorem (`scripts/validate_palette.js`) na powierzchniach TEJ aplikacji (`#ffffff` / `#09090b`), sześć slotów: tryb ciemny — wszystkie sześć kontroli PASS; tryb jasny — pasmo jasności, chroma, separacja CVD (ΔE 9,1) i widzenie normalne (ΔE 19,6) PASS, kontrast WARN (morski/żółty/magenta poniżej 3:1 wobec bieli). Ostrzeżenie jest świadomie przyjęte i pokryte wymaganym „reliefem": każdy wykres ma widoczne etykiety wartości ORAZ tabelę pod spodem, więc kolor nigdy nie jest jedynym nośnikiem informacji. **Zmiana tych hexów wymaga ponownego przebiegu walidatora.**

Żywa weryfikacja (`curl` + Playwright na 375 px, zrzuty w `frontend/test-results/struktura-*.png`): wszystkie cztery wymiary zwracają dane na realnym portfelu (bitcoin/XAU/CDR/PKN), etykiety po polsku (`crypto` → „Kryptowaluty", `gaming` → „Gaming", koszyk `nieznane` → „Nieznane"), portfel pusty daje `buckets: []` → stan pusty zamiast pustego wykresu, brak `?by=` to 422 (zgodnie z decyzją backendu). Dwie usterki znalezione i naprawione dopiero na zrzutach, nie przez testy: podziałki osi X zlewały się na 375 px („0,0% 20,0% 40,0%…" → `pctAxis` bez miejsc po przecinku i `splitNumber: 4`), a treemapa ucinała procent na wąskim kafelku („19,…" → font 11 px i `overflow: "break"`). Tryb ciemny zweryfikowany osobnym zrzutem — ECharts nie da się ostylować klasami `dark:`, więc to jedyne miejsce w UI, gdzie przełącznik motywu może cicho nie zadziałać.

### Backlog kroku 33 (nieblokujące)

- **Wybór wymiaru nie przeżywa wyjścia z widoku** — zwykły `useState`, bez URL ani `localStorage`. Świadomie: `?by=` w URL wymaga `useSearchParams` z granicą `Suspense`, a `localStorage` grozi rozjazdem hydratacji. Do rozważenia przy kroku 34, jeśli okaże się, że wraca się do jednego wymiaru częściej niż do innych.
- **`by=geo` nie odróżnia w UI koszyków z `country` od tych z `region`** — API tej informacji nie zwraca (`_bucket_key` zwraca gotowy string), więc nie da się oznaczyć takich wierszy bez zmiany backendu. Rozwiązane przypisem pod wykresem („grupowanie po kraju; gdy nieznany — po regionie"), co domyka wpis z backlogu analityki wyżej. Gdyby to okazało się mylące, właściwą naprawą jest dodatkowe pole w `AllocationBucketOut`, nie zgadywanie po stronie UI.
- **`by=market` świadomie pominięty w tym widoku** — rynki dostają własny panel z indeksami referencyjnymi w kroku 34 (`GET /portfolios/{id}/markets`), a sama alokacja indeksów nie zwraca. Typ `AllocationDimension` w `lib/analytics.ts` zawiera wszystkie pięć wartości z API; widok wybiera cztery.
- **`ValueChart` (krok 32) nie został przepisany na wspólny `EChart`** — działa i jest pokryty e2e, a przenoszenie go byłoby refaktorem poza zakresem kroku (CLAUDE.md 4.3). Konsekwencja: w repo są dwa wzorce cyklu życia ECharts. Do domknięcia przy kroku 34, jeśli i tam powstanie wykres.
- **Treemapa przy dwóch koszykach to słaba forma** (jeden szeroki kafelek + jeden wąski pasek) — plan wymieniał treemapę wprost, więc została, ale przy ≤3 walutach donut czytałby się lepiej. Do rozważenia po zobaczeniu realnych portfeli.
- ~~**Testy e2e struktury dopisane do `e2e/dashboard.spec.ts`, nie do osobnego pliku**~~ — powód (szósty `POST /auth/login` w oknie minuty = 429) **zniknął 2026-07-29**: dev/e2e ma `RATE_LIMIT_AUTH_PER_MINUTE=30`. Rozdzielenie tych scenariuszy na osobne pliki jest teraz możliwe i naturalnie wypada przy kroku 39.
- ~~**Nowe funkcje czyste to pierwsi realni kandydaci na Vitest**~~ — zrobione 2026-07-29: `lib/allocationLabels.test.ts` pokrywa `toChartSlices` (sortowanie, składanie nadmiaru w „Pozostałe", suma wag) i `bucketLabel` (nieznany klucz, koszyk `nieznane`).

## Krok 34 — panel „Twoje rynki" (zrobiony 2026-07-28) — ZAMYKA ETAP 6

Trasa `/portfolios/[id]/rynki` (Server Component → `MarketRankingPanel`, Client) plus `/rynki` z nawigacji głównej. Wiersz rynku: kod i nazwa, waga jako liczba i pasek postępu (czysty CSS — jedna wartość na wiersz nie potrzebuje kanwy), a pod spodem indeks referencyjny: symbol, wartość, zmiana d/d w kolorze wg znaku i sparkline do 30 ostatnich notowań.

**Rynek bez indeksu nie znika z listy i nie dostaje pustego wykresu** — pokazuje samą wagę z jednozdaniowym wyjaśnieniem (skill `analityka-struktury`). Widok nie odróżnia „rynek nie ma `index_asset_id`" od „ma, ale worker nie zaciągnął notowań", bo API tych przypadków nie rozróżnia (oba to `index: null`), a dla użytkownika znaczą to samo.

Sparkline jest **celowo neutralny kolorystycznie**, nie zielony/czerwony wg `change_1d`: seria pokazuje 30 notowań, a `change_1d` to jedna sesja — pomalowanie miesiąca kolorem ostatniego dnia sugerowałoby trend, którego ten kolor nie opisuje. Znak zmiany niesie liczba obok (`changeColorClass`). Oś Y sparkline'a idzie od `dataMin`, nie od zera — indeks o wartości kilkudziesięciu tysięcy spłaszczyłby się do prostej.

Nowe pliki: `lib/analytics.ts` (+`MarketRankingItem`/`MarketIndex`/`PricePoint`/`getMarketRanking`), `components/charts/MarketSparkline.tsx`, `components/markets/MarketRankingPanel.tsx`, `components/portfolio/PortfolioPicker.tsx`, `app/rynki/{layout,page}.tsx`, `app/portfolios/[id]/rynki/page.tsx`. Ekran wyboru portfela z kroku 33 wydzielony do `PortfolioPicker` i dzielony przez `/struktura` i `/rynki` — obie trasy różniły się wyłącznie segmentem URL i tekstami.

Żywa weryfikacja (`curl` + Playwright 375 px, zrzut `frontend/test-results/rynki-mobile-375.png`): portfel z bitcoinem, CDR, PKN i AAPL daje **CRYPTO 79,7% z indeksem `bitcoin` i serią 12 notowań** oraz **GPW 20,3% bez indeksu** (WIG20 nadal bez wierszy `prices` — patrz backlog danych rynkowych). `US` nie pojawia się w rankingu, bo AAPL nie ma w tym środowisku wyceny — zgodnie z zasadą „nie licz jako zero, wyklucz z mianownika". Oba warianty wiersza (z indeksem i bez) są więc pokryte żywymi danymi, nie tylko testem.

### Backlog kroku 34 (nieblokujące)

- **Asercja e2e na warianty wiersza jest sformułowana jako suma obu gałęzi** (`sparkline'y + wyjaśnienia == liczba wierszy`), a nie jako „GPW nie ma indeksu" — twarde przypisanie padłoby w dniu, w którym worker zaciągnie WIG20, mimo poprawnego kodu. To był ten sam błąd, który siedział w `test_market_ranking_happy_path_with_index` — **naprawiony 2026-07-29** (fixture `ranking_markets`, patrz backlog etapu 6).
- **Pierwsza wersja testu użyła `getByRole("listitem")` bez zawężenia i łapała pozycje dolnej nawigacji** (6 zamiast 2). Naprawione przez `aria-label="Rynki wg udziału w portfelu"` na liście — przy okazji realna poprawka dostępności. Warto sprawdzić, czy inne listy w UI też powinny mieć nazwę.
- **Sparkline nie ma tabelarycznej alternatywy** — decyzja: wszystkie liczby, które niesie (wartość indeksu, zmiana d/d, data notowania), są obok jako tekst, a tabela z trzydziestoma notowaniami na każdy rynek byłaby w tym miejscu szumem. Jeśli kiedyś pojawi się pełny wykres indeksu (krok 45, Lightweight Charts), tam alternatywa będzie obowiązkowa.
- **`GET /markets/{code}/index` (krok 30) nie ma dziś konsumenta we froncie** — panel korzysta z `series_30d` zaszytego w rankingu, co oszczędza N zapytań. Osobny endpoint przyda się dopiero przy wykresach świecowych (krok 45).
- ~~**`/dashboard` w nawigacji nadal jest linkiem placeholder**~~ — rozstrzygnięte 2026-07-29 na korzyść przekierowania: `app/dashboard/` używa `PortfolioPicker` z pustym `section`, tak samo jak `/struktura` i `/rynki`.

## Plan etapu 7 — wdrożenie produkcyjne (uzgodniony 2026-07-28, przed rozpoczęciem)

Etap zaplanowany na sesji 2026-07-28 (`/etap 7`). **Nie zaczęty. Blokada zdjęta:** etap 6 domknięty tego samego dnia (kroki 33 i 34), więc warunek z decyzji 1 poniżej jest spełniony i etap 7 można zaczynać od kroku 36.

**Decyzje użytkownika podjęte przy planowaniu:**

1. **Kolejność: najpierw domknąć etap 6 (kroki 33 i 34), dopiero potem cały etap 7 od 36 do 39.** Powód: krok 39 jest w planie zdefiniowany jako „wpisujesz pozycje, widzisz wartość, **skład %** i **ranking rynków**" — czyli dokładnie to, co dostarczają kroki 33 i 34. Bez nich smoke test nie ma czego sprawdzać, a Faza 1 nie może zostać formalnie zamknięta.
2. **Sentry: tak, backend + worker + frontend.** Zgoda na dwie nowe zależności zewnętrzne (`sentry-sdk[fastapi]`, `@sentry/nextjs`) — wymagana przez CLAUDE.md §10.
3. **Backup (krok 38): magazyn S3-compatible** (Backblaze B2 / Wasabi), wysyłka przez rclone/aws-cli.
4. **Zakres na VPS: tylko pliki i runbook.** Przygotowuję `Caddyfile`, compose produkcyjny, Dockerfile'e, skrypty i `docs/wdrozenie.md`; samo wdrożenie wykonuje użytkownik. Nie uruchamiam poleceń na produkcyjnym serwerze.

**Stan wyjściowy (zweryfikowany 2026-07-28):** istnieje wyłącznie `docker-compose.yml` w wersji dev (porty na zewnątrz, bind-mounty, `--reload`), oba Dockerfile'e są dev-owe. `Caddyfile`, `docker-compose.prod.yml`, `GET /api/health` i skrypt backupu **nie istnieją**. `sentry_dsn` jest w `core/config.py:82` i `.env.example`, ale żaden kod go nie czyta (`worker/jobs/ingest_market.py:199,267` — komentarze „Sentry w etapie 7"). Playwright zainstalowany, ale poza `make check` i bez scenariusza smoke. `.env` poprawnie nietrackowany.

**Krok 36 — Caddy + compose produkcyjny + migracje przed startem API** (agent `devops` + łatka od `backend-fastapi`)
`infra/caddy/Caddyfile` (auto-TLS, `/api/*` → `api:8000`, reszta → `frontend:3000`, HSTS i nagłówki bezpieczeństwa) · `docker-compose.prod.yml` (tylko Caddy wystawia 80/443, bez bind-mountów, healthchecki, jednorazowa usługa `migrate` z `alembic upgrade head`, `api` na `service_completed_successfully`) · produkcyjne targety w obu Dockerfile'ach (bez `requirements-dev`, nie-root, `uvicorn --proxy-headers` bez `--reload`; frontend `output: "standalone"` + `node server.js`) · `.env.prod.example` · cele `prod-*` w `Makefile` · `docs/wdrozenie.md`.
**Blokujące w tym kroku:** poprawka `core/rate_limit.py` — za Caddym `get_remote_address` widzi IP proxy, nie klienta (wpis z backlogu bezpieczeństwa niżej przestaje być nieblokujący). **Pułapka:** `NEXT_PUBLIC_API_URL` jest wypiekany na etapie `next build` — w produkcji ustawiamy względne `/api` (same-origin przez Caddy), co znosi też CORS; wymaga weryfikacji klienta API we `frontend/lib`.

**Krok 37 — Sentry + `/health` + alert workera** (`backend-fastapi` + `devops` + `frontend-next`, testy `qa-testy`)
Nowy publiczny `GET /api/health` wyłączony z rate limitu: liveness + readiness (`SELECT 1`, Redis `PING`), `{status, db, redis, version}`, bez wycieku szczegółów przy błędzie; podpięty jako healthcheck kontenera `api`; aktualizacja `docs/api-kontrakt.md`. Sentry inicjalizowane tylko gdy `SENTRY_DSN` niepusty (dev bez zmian), `send_default_pii=False`, scrubbing tokenów. Realizacja TODO z `ingest_market.py`: `status=failed` → `capture_message(level=error)`, `partial` → `warning`. Przy okazji warto domknąć brak fallbacku yfinance dla `WIG20` — inaczej GPW będzie generować powtarzalny alert.

**Krok 38 — nocny `pg_dump` poza VPS** (`devops`)
`infra/backup/backup.sh`: `pg_dump -Fc` → kompresja → znacznik czasu → wysyłka do bucketu S3 → retencja 7 dziennych / 4 tygodniowe → alert do Sentry przy niepowodzeniu. Harmonogram przez cron na hoście (nie job w APScheduler — przy padniętym API i tak by nie zadziałał). **Dopisane do zakresu ponad plan:** `make backup-restore-test` (odtworzenie ostatniego dumpu do jednorazowej bazy) — backup, którego nikt nie odtworzył, nie jest backupem. Sekcja „odtwarzanie z backupu" w `docs/wdrozenie.md`.

**Krok 39 — smoke test 375 px + desktop ← KONIEC FAZY 1** (`qa-testy` + `frontend-next`)
`frontend/e2e/smoke.spec.ts`: rejestracja → logowanie → portfel → pozycja → wartość → struktura % → ranking rynków; projekty Playwright `Mobile Chrome` @375 px i desktop; `make smoke` (poza `make check` — wymaga żywego stacku); ręczna lista kontrolna na prawdziwym telefonie. ~~Zależy od kroków 33 i 34~~ — odblokowane 2026-07-28, oba kroki zrobione, a `e2e/dashboard.spec.ts` pokrywa już całą ścieżkę wartości (jest realnym szkieletem tego smoke testu — przy kroku 39 raczej go rozdzielić i dołożyć projekt desktopowy niż pisać od zera). **Znany problem:** suita e2e zużywa dokładnie 5/5 slotów limitu `POST /auth/login` (wpis w backlogu etapu 6 niżej) — każdy nowy test z logowaniem da 429.

**Ryzyka do pilnowania przy realizacji:**
- Pierwsze wystawienie TLS: Let's Encrypt ma ostry limit błędów — start na staging CA, przełączenie na produkcyjne po zielonym przebiegu. Rekord A domeny musi wskazywać na VPS **przed** startem Caddy.
- `GOOGLE_REDIRECT_URI` dla produkcji trzeba dopisać w Google Cloud Console (`https://<domena>/api/auth/google/callback`) — akcja użytkownika.
- Worker na produkcji uderzy w prawdziwych dostawców; `/meta/freshness` może dawać fałszywe `stale=True` w weekend (wpisy w backlogu danych rynkowych niżej).
- Sekrety na VPS: nowy `SECRET_KEY` i hasło Postgresa (nie te z dev), `.env` z uprawnieniami 600, poza repo.
- Backup (krok 38) najlepiej uruchomić **zanim** w bazie produkcyjnej pojawią się realne dane.

**Kryterium ukończenia etapu 7:** wchodzisz na `https://<domena>` z telefonu, rejestrujesz się, tworzysz portfel, dodajesz pozycję — i widzisz wartość w PLN, skład procentowy i ranking rynków. `/api/health` zwraca `ok`. Restart VPS-a podnosi cały stack sam. Nocny dump leży poza VPS-em i został raz odtworzony. Błąd aplikacji ląduje w Sentry.

## Krok 36 — Caddy + compose produkcyjny (ZROBIONY 2026-07-29, niezacommitowany)

**Co powstało:** `backend/Dockerfile` i `frontend/Dockerfile` wielostopniowe (`dev`/`build`/`prod`,
nie-root, uvicorn bez `--reload`, Next standalone) · `frontend/next.config.ts` → `output: "standalone"` ·
`docker-compose.yml` (dev) z `target: dev` · `infra/caddy/Caddyfile` · `docker-compose.prod.yml` ·
`.env.prod.example` · cele `prod-*` w `Makefile` · `docs/wdrozenie.md` (runbook) ·
`seed_reference` + `python -m app.cli seed --reference-only`.

Wdrożenie na VPS wykonuje użytkownik (decyzja 4 z planu etapu) — tutaj są tylko pliki i procedura.

### Blokujące z code-review — naprawione

1. **`api` bez polityki restartu** → `restart: unless-stopped`. Druga połowa znaleziska (`depends_on`
   nie działa przy starcie demona po reboocie, więc `migrate` by się nie wykonał) rozwiązana **jednostką
   systemd**, nie polityką kontenerów: `docs/wdrozenie.md` §7 podnosi cały stack jednym `compose up`,
   co odtwarza kolejność zależności.
2. **`POSTGRES_*` nie pochodziło z `.env.prod`.** Usługa `postgres` dostała `env_file: .env.prod`
   (zmienne trafiają do WNĘTRZA kontenera), healthcheck używa `$$POSTGRES_USER` (rozwijane w kontenerze,
   nie na hoście), a wszystkie cele `prod-*` mają zaszyte `--env-file .env.prod`. Zweryfikowane
   `docker compose config`: z wypełnionym hasłem w `.env.prod` dociera ono do wszystkich czterech miejsc.
3. **Healthcheck `api` odpytywał nieistniejący `/api/health`** (to krok 37) → tymczasowo sprawdzenie
   gniazda (`socket.create_connection` na 8000) z komentarzem odsyłającym do kroku 37. Wybrałem to
   zamiast przenoszenia endpointu przed krok 36: `/api/health` to readiness z `SELECT 1` i Redis `PING`,
   część kontraktu kroku 37 razem z Sentry — nie ma powodu robić go po kawałku. Podmiana testu przy
   kroku 37 to jedna linia.
4. **`COPY /app/public` przy nietrackowanym, pustym `frontend/public/`** → `RUN mkdir -p public` w stopniu
   `build` (działa na każdym klonie, nie wymaga pilnowania pliku `.gitkeep`).
5. **`.env.prod.example` nie do zacommitowania** → `!.env.prod.example` w `.gitignore`, z komentarzem, że
   każdy kolejny `.env.<środowisko>.example` potrzebuje własnego wyjątku.
6. **Brak seeda słownika rynków na produkcji.** `app/db/seed.py` rozdzielony: `seed_reference` (rynki,
   indeksy referencyjne, mapowania dostawców) i `seed_all` (to samo + demo użytkownik/portfel/pozycje).
   `make prod-seed` woła wariant referencyjny i **sam restartuje workera**, bo `worker/scheduler.py`
   czyta `markets` raz przy starcie. Produkcja nie dostaje demo użytkownika z hasłem wypisywanym na
   konsolę ani cudzych pozycji w bazie.

### Znalezione dopiero przy realnej budowie obrazów

7. **`useradd --create-home --uid 1000 app` w stopniu `prod` frontendu wywalał build** (kod 4, „UID
   already in use") — obraz `node:22-slim` ma konto `node` z UID 1000 od zawsze, w odróżnieniu od
   `python:3.12-slim`, gdzie 1000 jest wolne. Zamienione na `USER node` i `--chown=node:node`.
   **Ten błąd nie wyszedłby z żadnej analizy statycznej ani `docker compose config`** — dopiero
   `docker compose build` go pokazał. To argument za wpisem „CI nie buduje obrazów" niżej.

**Weryfikacja (2026-07-29):** `docker compose config` przechodzi; oba obrazy `prod` budują się na drzewie
BEZ katalogu `frontend/public` (symulacja świeżego klona); `docker run` potwierdza nie-roota
(`uid=1000(node)` i `uid=1000(app)`), `import app.main` w obrazie API przechodzi, kontener frontendu
oddaje `/login` z kodem 200. `make check` zielony, `make seed` i `seed --reference-only` obie działają.

### Nieblokujące, świadomie zostawione

- ~~`caddy` czeka na `api: service_healthy`~~ — **domknięte w kroku 37**: `service_started` dla `api`
  i `frontend`. Od kiedy healthcheck realnie odpytuje bazę, „API niezdrowe" znaczy „Postgres jeszcze
  nie wstał", a Caddy czekałby wtedy w nieskończoność — kładąc TLS i frontend przez awarię backendu.
- ~~Brak `logging: max-size`~~ — **domknięte w kroku 37**: kotwica YAML `x-logging` (10 MB × 5) na
  wszystkich pięciu usługach. W repo, nie w `/etc/docker/daemon.json` — limit ma przetrwać odtworzenie
  VPS-a od zera.
- ~~**CI nie robi `docker build --target prod`**~~ — **domknięte w kroku 37**: job `obrazy-prod`
  w `.github/workflows/ci.yml` buduje oba obrazy w stopniu `prod`.
- ~~`NEXT_PUBLIC_SENTRY_DSN` nie dotrze do frontendu~~ — **domknięte w kroku 37**: przeszedł do `args:`
  w `docker-compose.prod.yml` i `ARG`/`ENV` w `frontend/Dockerfile`.
- `172.28.0.10` leży w dynamicznej puli IPAM (przydałby się `ip_range`); `backend/.dockerignore` nie
  wyklucza `tests/`, `.claude/`, `.tokensave/`; brak CSP w Caddyfile; Redis bez `--save ""`; brak
  `cap_drop`/`no-new-privileges`; uvicorn bez `--workers` (na jednym VPS-ie prawdopodobnie słusznie);
  hasło Postgresa zduplikowane w `.env.prod.example` (`POSTGRES_PASSWORD` i w `DATABASE_URL`).
- HSTS przy `TLS_MODE=internal`/`DOMAIN=localhost` przypiąłby `localhost` do HTTPS na rok i zatruł dev.
  Runbook nie każe nigdzie uruchamiać produkcyjnego stacku pod `localhost`, więc zostaje jak jest —
  ale gdybyś chciał spróbować lokalnie, użyj domeny typu `alphasense.test`, nie `localhost`.

**Zostaje w etapie 7:** krok 39 (smoke test).

## Krok 37 — Sentry + `/api/health` + alerty (ZROBIONY 2026-08-03)

**Co powstało:** `app/core/observability.py` (`init_sentry(component)`, jedna inicjalizacja dla API,
workera i CLI) · `app/core/health.py` (`GET /api/health`) · Sentry we froncie
(`instrumentation-client.ts`, `instrumentation.ts`, `sentry.server.config.ts`, `withSentryConfig`
w `next.config.ts`) · alerty ingestii w `worker/jobs/ingest_market.py` · rotacja logów i healthcheck
readiness w `docker-compose.prod.yml` · job `obrazy-prod` w CI · `APP_VERSION` w obu `.env*.example`.

**Sentry jest wyłączone, dopóki `SENTRY_DSN` jest pusty** — dev, `make check` i Playwright nie robią
ani jednego żądania sieciowego do Sentry. Dwa projekty (backend + frontend), bo DSN frontendowy jedzie
do przeglądarki każdego użytkownika i nie jest sekretem, a backendowy jest. API i worker dzielą jeden
DSN, rozróżniane tagiem `component` (`api`/`worker`/`cli`) — inaczej nie dałoby się odfiltrować awarii
jobów EOD od błędów żądań HTTP. `send_default_pii=False` plus `max_request_body_size="never"`: ciało
`POST /auth/login` niesie hasło jawnie, a scrubber działa na polach o znanych nazwach, nie na surowym
bajcie ciała. Tracing (`traces_sample_rate=0`) świadomie wyłączony — ten krok to alerty o awariach,
nie profilowanie, a każda transakcja zjada limit darmowego planu.

**Job EOD raportuje jawnym `capture_message`, nie przez logi.** `structlog` w tym repo pisze **poza**
`logging`, więc `LoggingIntegration` nie widzi naszych `logger.error(...)` — gdyby nie jawne wywołanie,
alerty operacyjne byłyby cichą fikcją. `status=failed` → poziom `error` (rynek nie ma dziś ŻADNYCH
świeżych danych, wycena policzy się na wczorajszych cenach i nikt się nie dowie), `partial` → `warning`.
`fingerprint` po rynku i statusie: powtarzalna awaria jednego rynku to JEDEN problem z licznikiem,
nie nowa sprawa każdej doby.

**`GET /api/health` zawsze oddaje `200`** — o zdrowiu decyduje ciało (`{status, db, redis, version}`).
Padnięty Redis daje `degraded`, ale kontener zostaje ZDROWY, bo aplikacja bez cache'a działa dalej
(CLAUDE.md #3.7); healthcheck w compose czyta pole `db`, nie kod HTTP i nie `status`. Trasa jest
publiczna, więc niesie wyłącznie `up`/`down` — komunikat wyjątku (host bazy, wersja Postgresa) idzie
do logów i Sentry, nie do odpowiedzi. Wyłączona z limitu domyślnego przez
`DEFAULT_LIMIT_EXEMPT_PATHS`, a nie `@limiter.exempt` — ten dekorator byłby tu adnotacją, która wygląda
na zabezpieczenie i nim nie jest (limit domyślny nakłada middleware, nie slowapi).

### Znalezione przy okazji — dwa defekty spoza zakresu kroku

1. **Limit domyślny nie działał ani na jednej trasie od czasu FastAPI 0.139** (regresja kroku 16,
   wykryta przy pisaniu zwolnienia dla `/api/health`). `SlowAPIMiddleware` szuka handlera przez
   `_find_route_handler(app.routes, scope)`, a FastAPI 0.139 nie spłaszcza już `include_router` do
   `APIRoute` — wstawia `_IncludedRouter` bez atrybutu `endpoint`. Handler nigdy się nie znajdował,
   a `_should_exempt` traktuje `handler is None` jako „zwolnione z limitu": middleware przepuszczało
   **wszystko**, cicho i wyglądając na działające (130 żądań w 0,3 s bez jednego `429` i bez śladu
   w Redisie). Ta sama zmiana routingu, która w etapie 5 cicho zepsuła harness `test_isolation.py`.
   Naprawione własnym `DefaultRateLimitMiddleware` (`INCR`/`EXPIRE`, okno stałe) zamiast kolejnej
   zależności od wewnętrznych mechanizmów cudzej biblioteki. Limity `/auth/*` (dekorator) działały
   i działają — to one chronią hasła, limit domyślny to grubszy bezpiecznik przeciwzalewowy.
   **Awaria Redisa obsługiwana różnie w każdej warstwie, świadomie**: `/auth/*` zwraca błąd (inaczej
   otwarta droga do brute-force), limit domyślny przepuszcza ruch z logiem `warning` (inaczej awaria
   cache'a staje się awarią całego API).
2. **Testy przechodziły przez podwójnego Redisa, który nie miał `incr`/`expire`.** `_BrokenRedis`
   w `tests/integration/test_rate_limit.py` mockował tylko `get`/`set`, więc nowy middleware wywalał
   się na nim `AttributeError` zamiast degradować. Doszedł test „limit domyślny przepuszcza ruch przy
   padniętym Redisie" — najważniejsza gwarancja tej warstwy, więc pokryta wprost.

**Fallback WIG20** (`yfinance`, `WIG20.WA`) dopisany do `SOURCE_MAPS`: WIG20 był JEDYNYM aktywem GPW
bez drugiego dostawcy, więc każda odmowa Stooqa kończyła rynek statusem `partial` — a od tego kroku
`partial` to alert, więc powtarzalny brak fallbacku nauczyłby ignorować alerty. Symbol zweryfikowany
na żywo (`^WIG20`/`WIG20` u yfinance nie istnieją, `WIG20.WA` zwraca notowania).

**Żywa weryfikacja** (dev stack, 2026-08-03): `make check` zielone (**247 passed**, ruff, mypy strict
55 plików, Vitest 29, `next build`), Playwright **5/5**. `GET /api/health` → `{"status":"ok","db":"up",
"redis":"up","version":"0.1.0"}`. **120 żądań na `/api/health` → 120× `200`** (zwolnienie działa),
**120 na `/api/meta/freshness` → 100× `200` + 20× `429`** (limit domyślny egzekwowany dokładnie na
setce — dowód, że naprawa z punktu 1 wyżej realnie działa, nie tylko w teście). `ingest --market GPW`
→ `status=ok`, 3/3 aktywa, w tym WIG20 przez fallback yfinance przy otwartym obwodzie Stooqa.

### Backlog kroku 37 (nieblokujące)

- **Dwa DSN-y Sentry wciąż nieustawione** (patrz „Decyzje oczekujące") — cały tor jest zweryfikowany
  wyłącznie w trybie wyłączonym. Realne dostarczenie zdarzenia do projektu Sentry pozostaje
  niezweryfikowane; naturalny moment na sprawdzenie to pierwsze wdrożenie (krok 39).
- **`APP_VERSION` domyślnie `0.1.0` i nikt go na produkcji nie ustawi automatycznie** — runbook każe
  wpisać `$(git rev-parse --short HEAD)` ręcznie. Do rozważenia przy kroku 39: wyliczać w `make prod-build`.
- **Source mapy frontendu nie lecą do Sentry bez `SENTRY_AUTH_TOKEN`** — ślady stosu z przeglądarki
  będą zminifikowane. Włącza się samo po uzupełnieniu trzech zmiennych, bez zmiany w kodzie.
- **`/api/health` nie sprawdza workera.** Padnięty scheduler nie zmienia odpowiedzi — widać go dopiero
  przez `/meta/freshness` (`stale=True`). Świadomie: healthcheck kontenera `api` nie ma powodu padać
  z powodu innego kontenera. Osobny healthcheck workera to kandydat na krok 38/39.
- **Okno stałe zamiast przesuwnego w limicie domyślnym** — dopuszcza krótki skok na styku dwóch okien
  (do 2× limitu przez chwilę). Dla bezpiecznika przeciwzalewowego bez znaczenia; `/auth/*` zostaje na
  przesuwnym oknie slowapi, bo tam precyzja realnie chroni hasła.
- **Baza dev miała 22 osierocone aktywa testowe** (`HOLP*`/`HOLU*`/`TEST-*`) z przerwanych przebiegów
  sprzed napisania teardownów — przez nie GPW kończył `partial` mimo zdrowych danych, czyli stały
  fałszywy alert. Usunięte ręcznie 2026-08-03. Sprawdzone, że wyciek **nie jest aktywny**: `pytest
  tests/integration/test_holdings.py` przed i po daje ten sam licznik (22 → 22). Zmiana w kodzie
  niepotrzebna, ale warto o tym pamiętać, gdy `/meta/freshness` znów pokaże dziwny rynek.

## Krok 38 — nocny `pg_dump` poza VPS (ZROBIONY 2026-08-03)

**Co powstało:** `infra/backup/backup.sh` (dump → weryfikacja → wysyłka do bucketu → retencja) ·
`infra/backup/restore-test.sh` (odtworzenie ostatniej kopii do jednorazowej bazy) ·
`infra/backup/common.sh` (wspólne ładowanie `.env.prod`, `aws` z obrazu, alert) ·
`infra/backup/alphasense-backup.cron` · `make backup` i `make backup-restore-test` ·
`python -m app.cli alert` + `tests/unit/test_cli_alert.py` · sekcja backupu w `.env.prod.example` ·
`docs/wdrozenie.md` §9 (konfiguracja, harmonogram, test odtworzenia, pełne odtworzenie produkcji).

**Dopisane 2026-08-03 przy podłączaniu prawdziwego bucketu:** `infra/backup/check-bucket.sh`
(`make backup-check`) — pełny obieg na obiekcie próbnym: zapis, listowanie, kopia serwerowa, odczyt
**z porównaniem treści**, kasowanie, plus ostrzeżenia o publicznym buckecie i braku reguły cyklu życia.
Powód: `aws s3 ls` sprawdza jedną operację z pięciu. Klucz bez prawa kasowania przechodzi `s3 ls`
i wywala się dopiero na retencji — czyli ósmej nocy, w logu crona, którego nikt nie czyta.

Przy tej okazji wyszedł **błąd, którego weryfikacja kroku 38 nie mogła złapać**: domyślny obraz
`amazon/aws-cli:2` nie istnieje w rejestrze (są tylko `latest`, `amd64`, `arm64` i pełne `2.x.y`), więc
**każda** wysyłka do bucketu padłaby na `docker: not found`. Nie wyszło wcześniej, bo przy pustych
`BACKUP_S3_*` skrypt w ogóle nie dotyka `aws` — cała ścieżka S3 była nieprzetestowana aż do dziś.
Naprawione przypięciem `amazon/aws-cli:2.36.14` (`common.sh`, `docs/wdrozenie.md`, ten plik). Przypięta
wersja, nie `latest`: w ścieżce backupu nowe wydanie obrazu mogłoby zepsuć odtwarzanie dokładnie w dniu,
w którym jest potrzebne.

**Cała ścieżka S3 przeszła test end-to-end na żywym B2 (2026-08-03)** — przez stack DEV
(`BACKUP_COMPOSE_FILE=docker-compose.yml ENV_FILE=.env`) i na osobnym prefiksie `_e2e`, żeby dump z deva
nie mógł nigdy trafić pod `alphasense/daily/` i zostać wzięty za produkcyjną kopię. Sprawdzone:
dump → `pg_restore --list` → wysyłka pod `daily/` → retencja; następnie awans niedzielny (`date -u +%u`
podstawiony na 7) → kopia serwerowa do `weekly/` → retencja dzienna obniżona do 1 skasowała **starszą**
z dwóch kopii; na koniec `restore-test.sh` ściągnął najnowszą kopię Z BUCKETU, odtworzył ją do
jednorazowej bazy (`alembic=a2f2b11877d4`, 12 rynków) i po sobie posprzątał. Prefiks `_e2e` skasowany
razem z wersjami — bucket jest pusty.

**Skrypty jadą z HOSTA, nie z workera.** Backup w APSchedulerze byłby kontenerem tego samego stacku —
awaria, po której backup jest najbardziej potrzebny (padnięta aplikacja, pełny dysk, pętla restartów),
zabrałaby ze sobą także backup. Cron hosta przeżywa padnięty stack.

**Jedyną zależnością na VPS-ie jest Docker.** `pg_dump`, `pg_restore` i `aws` biorą się z obrazów
(`postgres:16` — dokładnie ten sam, na którym stoi baza, oraz `amazon/aws-cli:2.36.14`), więc nie ma czego
instalować ani pilnować: `pg_dump` starszy od serwera odmawia pracy, a to jest ten rodzaj awarii, który
wychodzi dopiero w dniu odtwarzania. Klucze do bucketu jadą do kontenera przez `-e NAZWA` (wartość z
otoczenia, nie z argumentów) — nie widać ich w `ps aux` ani w `docker inspect`.

**Dump jest weryfikowany od razu po powstaniu** (`pg_restore --list` na świeżym pliku). Rozmiar > 0 nie
znaczy „czytelny": przerwany `pg_dump` zostawia plik, który wygląda normalnie do dnia, w którym trzeba
z niego odtworzyć bazę. Niedokończony dump jest kasowany przez trap — zostawiony, byłby przy odtwarzaniu
wybrany jako „najnowszy".

**Retencja liczona w SZTUKACH kopii (7 dziennych, 4 tygodniowe), nie w dniach.** Reguła wiekowa
(„kasuj starsze niż 7 dni") przy zatrzymanym cronie skasowałaby po tygodniu również ostatnią zdrową
kopię — czyli awaria harmonogramu zamieniałaby się w utratę backupu. Przy liczeniu sztuk zepsuty cron
co najwyżej zostawia stare dumpy. Kopia tygodniowa powstaje w niedzielę **kopiowaniem serwerowym**
w obrębie bucketu, bez drugiej wysyłki przez łącze VPS-a.

**`make backup-restore-test` ściąga kopię Z BUCKETU, nie bierze lokalnej** — testujemy tę, która
przeżyje utratę VPS-a. Odtwarza do bazy `restore_test_<znacznik>` obok produkcyjnej, porównuje
`alembic_version` z bazą żywą (dump sprzed migracji, która już poszła na produkcję, postawi bazę,
na której API nie wstanie), sprawdza, że słownik rynków nie jest pusty, i **zawsze** kasuje bazę
testową (trap + wzorzec nazwy sprawdzany przed `dropdb`). `pg_restore` dostaje `--exit-on-error`:
domyślnie wypisuje błędy poszczególnych poleceń i **kończy się kodem 0**, więc bez tej flagi test
przechodziłby na dumpie, z którego odtworzyła się połowa tabel.

**Alerty przez `python -m app.cli alert`, nie `curl`-em na API Sentry.** DSN, `release` i `environment`
są konfiguracją aplikacji (`core/observability.py`); składanie koperty w bashu byłoby drugim,
rozjeżdżającym się miejscem z tą wiedzą. Nowy tag `component=infra` odróżnia awarię nocnego backupu od
wyjątku w żądaniu użytkownika. Fingerprinty (`backup-failed`, `backup-restore-failed`,
`backup-s3-not-configured`) — powtarzalna awaria to jeden problem z licznikiem, nie nowa sprawa co noc
(ta sama zasada, co przy alertach ingestii z kroku 37). Druga, niezależna droga powiadomienia to poczta
crona do roota: przy pustym `SENTRY_DSN` zostaje poczta, przy padniętym MTA zostaje Sentry.

**Puste `BACKUP_S3_*` nie wyłączają backupu po cichu** — dump powstaje lokalnie, a skrypt wysyła
ostrzeżenie „kopia leży tylko na VPS-ie". Cicha wersja tego stanu to dokładnie ten backup, którego nie
ma w dniu awarii.

**Żywa weryfikacja (2026-08-03, przeciw stackowi dev)** — skrypty mają `BACKUP_COMPOSE_FILE` właśnie po
to, żeby dało się je przepuścić przez dev, a nie sprawdzać po raz pierwszy na produkcji:
`backup.sh` → dump 27 KiB, `pg_restore --list` przechodzi, plik dostaje `600`; `restore-test.sh` →
`alembic=a2f2b11877d4`, `markets=12`, `prices=73`, baza testowa utworzona i usunięta (`pg_database`
po przebiegu bez śladu); retencja lokalna przy trzech dumpach i limicie 2 kasuje najstarszy;
**ścieżka awarii** (podstawiona nieistniejąca baza) kasuje niedokończony plik, woła alert i kończy się
kodem 1; obcięty dump (4 kB) jest przez `pg_restore --list` odrzucany, czyli strażnik z punktu wyżej
realnie działa. `shellcheck` (obraz `koalaman/shellcheck:stable`) czysty na wszystkich trzech skryptach.
`make check` zielony: **251 testów** backendu, ruff, mypy strict 55 plików, Vitest 29, `next build`.

### Backlog kroku 38 (nieblokujące)

- **Nikt nie zauważy, że cron w ogóle nie wystartował.** Alert leci przy awarii przebiegu, ale usunięty
  wpis w `/etc/cron.d`, wyłączony demon crona albo padnięty VPS nie generują żadnego zdarzenia —
  cisza wygląda identycznie jak sukces. Właściwe narzędzie to Sentry Crons (check-in „miałem się odezwać
  do 06:00"), do rozważenia razem z DSN-ami przy pierwszym wdrożeniu. Namiastką jest plik
  `$BACKUP_DIR/last-success` ze znacznikiem czasu ostatniego udanego przebiegu.
- **`shellcheck` nie jest w `make check` ani w CI** — uruchamiany ręcznie przez obraz Dockera. Dopięcie
  go do joba w CI to kilka linii, ale to zmiana pipeline'u poza zakresem tego kroku.
- **Test odtworzenia dzieli instancję Postgresa z produkcją** — na jednym VPS-ie nie ma alternatywy,
  ale zjada miejsce na dysku równe rozmiarowi bazy i konkuruje o CPU. Stąd raz w tygodniu i o 06:30,
  nie po każdym backupie. Przy realnie dużej bazie przenieść na osobną maszynę.
- **Retencja nie zna „miesięcznych"** — 7 dziennych i 4 tygodniowe dają zasięg ok. miesiąca. Cicha
  korupcja danych sprzed dwóch miesięcy jest z tego nieodtwarzalna. Do rozważenia, gdy w bazie pojawi
  się historia, na której realnie zależy.
- **Skrypty zakładają `bash` i GNU `find`/`stat`** (`-printf`, `stat -c`) — działają na Debianie/Ubuntu,
  poległyby na Alpine albo BSD. VPS z runbooka jest Debianowy, więc świadomie bez warstwy zgodności.
- **Dump nie jest szyfrowany po stronie klienta.** Leci przez TLS i leży w prywatnym buckecie, ale
  dostawca magazynu technicznie widzi zawartość — łącznie z hashami haseł i tokenami odświeżającymi.
  Szyfrowanie GPG przed wysyłką to kilka linii, ale wprowadza klucz, którego utrata unieważnia wszystkie
  kopie; decyzja użytkownika, nie domyślne zachowanie.

## Krok 39 — smoke test 375 px + desktop (ZROBIONY 2026-08-05)

**Co powstało:** `frontend/e2e/smoke.spec.ts` · projekt `desktop` (1280×900) w `playwright.config.ts`
obok istniejącego `mobile-375` · `make smoke` · `docs/wdrozenie.md` §10 (automat + ręczna lista
kontrolna na prawdziwym telefonie + sprzątanie konta smoke z bazy produkcyjnej) · wolumen anonimowy
`/app/.next` w `docker-compose.yml` (patrz „Znalezione przy okazji" niżej).

**Wszystko idzie przez UI — ani jednego żądania do API składanego z boku.** To jedyna różnica, która
naprawdę się liczy wobec `dashboard.spec.ts` (ten przygotowuje portfel i pozycje przez `request`,
bo pokrywa komponenty, nie ścieżkę). Dzięki temu ten sam plik da się puścić na produkcję —
`E2E_BASE_URL=https://alphasense.cedron.net.pl make smoke` — gdzie nie mamy ani tokenu, ani prawa
dopisywania czegokolwiek do bazy z boku.

**Test biegnie w DWÓCH projektach i sam nie ustawia rozmiaru okna** (bierze go z projektu), w
odróżnieniu od `dashboard.spec.ts`, który przełącza viewport w trakcie. Konsekwencja: nawigacja jest
klikana przez „ten link, który akurat widać" (`filter({ visible: true })`), więc na 375 px sprawdza
`BottomNav`, a na desktopie `SideNav` — dwa różne komponenty, ta sama asercja. Desktop dostaje
**wyłącznie** smoke (`testMatch`); puszczanie tam całej suity podwoiłoby czas i liczbę logowań, nic
nowego nie sprawdzając.

**Asercja na wartość portfela jest na NIEZEROWĄ kwotę**, nie na obecność napisu „zł". „0,00 zł" to
dokładnie ten stan, w którym aplikacja wygląda na działającą, a produkt nie działa: pozycja siedzi
w bazie, ale wycena nie ma z czego powstać (brak `prices`, brak kursu NBP, worker nigdy nie odpalił).
Po świeżym wdrożeniu to najbardziej prawdopodobna czerwona asercja i **zwykle nie jest błędem kodu** —
worker rejestruje joby EOD przy starcie i czeka na swoją godzinę (ADR-102). Wymuszenie ingestii jest
w runbooku §10.1.

**Aktywo jest parametrem (`E2E_SMOKE_ASSET`, domyślnie `bitcoin`)**, bo produkcja dostaje sam
`seed_reference` — są w niej indeksy rynków, nie ma demo CDR/PKN/AAPL. `bitcoin` to jedyne aktywo
obecne w OBU środowiskach (jest indeksem rynku CRYPTO i jednocześnie normalnym `Asset`).

**Żywa weryfikacja (2026-08-05, stack dev):** `make smoke` → 2/2 zielone (mobile 375 px i desktop),
pełna suita `npx playwright test` → **7/7** (5 dotychczasowych + 2 smoke, zero regresji).
Zrzuty `frontend/test-results/smoke-{mobile-375,desktop}-{wartosc,struktura,rynki}.png` — na wariancie
mobilnym realne **12 194,86 zł** za 0,05 BTC, wykres kołowy alokacji, tabela udziałów i lista rynków.

### Znalezione przy okazji — rozjazd `.next` naprawiony u przyczyny

Pierwszy przebieg smoke testu padł na **HTTP 404 na `/portfolios/{id}/struktura`** przy w pełni
działających `/portfolios/{id}` i `/struktura`. Trasy istniały, były w manifeście buildu, a mimo to
dev-serwer oddawał stronę „not found" — to trzecia twarz znanego problemu ze współdzielonym `.next`
(poprzednie dwie: `ChunkLoadError` i HTTP 500 na każdej trasie, „Notatki operacyjne"). Przyczyna:
`make check` uruchamia `next build` NA HOŚCIE, kontener biegnie `next dev`, a `./frontend:/app` daje
obu stronom ten sam katalog.

Naprawione **wolumenem anonimowym `/app/.next`** w `docker-compose.yml` — ten sam wzorzec, którym repo
już odcina `node_modules`. Kontener ma własne `.next`, host własne, żadne nie widzi drugiego.
Zweryfikowane sekwencją, która wcześniej niezawodnie psuła dev-serwer: `make check` (pełny hostowy
`next build`) → natychmiast `npx playwright test` → 7/7 zielone.

Odrzucona alternatywa: `distDir` przestawiane zmienną `NEXT_DIST_DIR` w `next.config.ts`. Działa, ale
ciągnie ogon — ESLint zaczyna czytać wygenerowany kod (kilkadziesiąt błędów `no-require-imports`
z cudzych bundli), a `next build` **sam dopisuje** nowy katalog do `include` w `tsconfig.json`.
Naprawa jednego pliku kosztowałaby zmiany w czterech.

### Backlog kroku 39 (nieblokujące)

- **Domyślny `expect.timeout` podniesiony do 10 s** dla całej suity. Powód: jeden przebieg smoke padł
  po recreate kontenera, gdy Turbopack kompilował trasę przy pierwszym wejściu. False negative
  w smoke teście jest droższy niż kilka sekund czekania — to on decyduje, czy wdrożenie uznajemy za
  udane. Gdyby okazało się, że maskuje realną powolność, właściwą naprawą jest osobny, dłuższy timeout
  tylko dla `smoke.spec.ts`.
- **Smoke na produkcji zostawia konto** `smoke-…@alphasense.example` z portfelem i pozycją. Sprzątanie
  jest ręczne (`DELETE FROM users WHERE email LIKE 'smoke-%'`, runbook §10.1) — automat wymagałby
  endpointu kasującego konto, którego nie ma i który jest poza zakresem Fazy 1.
- **Playwright emuluje rozmiar okna, nie telefon.** Klawiatura systemowa, przecinek z polskiej
  klawiatury w polu ilości, gesty i chowający się pasek adresu są w ręcznej liście kontrolnej §10.2,
  bo automat ich nie dotyka.
- **`make smoke` nie jest w CI** — wymaga żywego stacku, a CI ma sam kod. Naturalne miejsce to job CD
  (jeśli zostaje) jako krok po `prod-up`, zamiast dzisiejszego `curl` na `/api/health`, który przy
  zawsze-200 z założenia niczego nie dowodzi.
- ~~**Testy e2e struktury dopisane do `dashboard.spec.ts`**~~ — powód (limit logowań) zniknął
  2026-07-29, a rozdzielenie „naturalnie wypada przy kroku 39". **Świadomie NIE zrobione**:
  `dashboard.spec.ts` przechodzi i pokrywa komponenty, a przepisywanie go byłoby refaktorem poza
  zakresem kroku (CLAUDE.md §4.3). Smoke test i tak pokrywa tę ścieżkę niezależnie, w dwóch
  rozmiarach okna.

## Wdrożenie ciągłe (CD) — trzy blokujące z code-review naprawione 2026-08-05

Job `deploy` w `ci.yml` pojawił się poza planem etapu 7 i code-review dał na nim trzy blokujące.
Wszystkie zamknięte; decyzja zapisana jako **[ADR-103](docs/adr/ADR-103-wdrozenie-ciagle.md)**
(zmienia decyzję 4 planu etapu 7 — „tylko pliki i runbook").

**1. Klucz SSH nie jest już równoważny rootowi.** Powstał `infra/deploy.sh` — jedyne polecenie,
które klucz z GitHuba może uruchomić (`restrict,command="…/infra/deploy.sh"` w `authorized_keys`).
Treść polecenia przysłana przez klienta nie jest wykonywana: ląduje w `SSH_ORIGINAL_COMMAND` jako
string i jest walidowana regexem `^[0-9a-f]{40}$`. Wcześniej `ssh user@host "<cokolwiek>"` dawało
wykonanie dowolnego kodu jako root na maszynie z `.env.prod` (SECRET_KEY, hasło Postgresa,
`GOOGLE_CLIENT_SECRET`, klucz do bucketu B2 **z prawem kasowania kopii**).

**2. Sprawdzenie po wdrożeniu realnie coś sprawdza.** `curl --fail` na `/api/health` przechodziło
także przy `db: down`, bo ta trasa z założenia zawsze oddaje `200` (krok 37). Teraz są dwa
niezależne sprawdzenia: `deploy.sh` czeka, aż kontener `api` zgłosi się jako `healthy` (healthcheck
compose'a parsuje pole `db` — reużyty werdykt, nie druga kopia tej logiki), a job w CI odpytuje
`https://…/api/health` z zewnątrz i **parsuje ciało** przez `jq` (`status == "ok" and .db == "up"`),
z dziesięcioma próbami co 10 s. Zewnętrzne sprawdzenie mierzy co innego niż wewnętrzne: DNS, TLS,
Caddy i proxy na `/api/*`.

**3. Decyzja zapisana.** ADR-103 wraz z kosztami: kto może wypchnąć na `main`, ten wdraża
(ochroną jest branch protection, nie ten skrypt), a dopóki `make smoke` nie jest częścią tej
ścieżki, jedynym dowodem poprawności jest „proces żyje i widzi bazę", nie „produkt działa".

**Domknięte przy okazji, bo pisanie `deploy.sh` i tak wymagało rozstrzygnięcia tych miejsc:**
ponowne uruchomienie starego przebiegu nie cofa produkcji (commit musi być przodkiem `origin/main`
**i** nowszy niż wdrożony), repo zostaje na gałęzi `main` zamiast w detached HEAD (ręczne `git pull`
z runbooka §8 nadal działa), `APP_VERSION` ustawia się sam na skrót SHA (bez tego `release`
w Sentry zamarzłby na `0.1.0` — backlog kroku 37 klasyfikował to jako nieblokujące **przy
wdrożeniach ręcznych**), `make prod-seed` tylko przy realnej zmianie `seed.py` (bezwarunkowy restart
workera mógł trafić w okno ingestii EOD i sam wygenerować alert `failed`), `flock` przeciw dwóm
wdrożeniom naraz, `timeout-minutes: 30`, `permissions: {}` i `BatchMode`/`IdentitiesOnly` w jobie.

**Ścieżka repo na VPS-ie ujednolicona na `/opt/alphasense/Alphasense`** (potwierdzona przez
użytkownika): `docs/wdrozenie.md` §1, jednostka systemd §7, §8 i **`infra/backup/alphasense-backup.cron`**
wskazywały na `/opt/alphasense`, więc nocny backup i test odtworzenia nie znalazłyby swoich skryptów.

**Weryfikacja (2026-08-05):** `shellcheck` czysty, `bash -n` OK, workflow parsuje się do poprawnego
YAML-a. Logika sprawdzona w piaskownicy (klon repo + podstawione `make`/`docker` na `PATH`, żeby nie
sprawdzać jej po raz pierwszy na produkcji): próba wstrzyknięcia `"cokolwiek; rm -rf /"` odbita przed
dotknięciem czegokolwiek, skrócony SHA odbity, commit spoza `origin/main` odbity, commit starszy niż
wdrożony odbity, ten sam commit → „nic do zrobienia", ścieżka szczęśliwa kończy się na gałęzi `main`
z ustawionym `APP_VERSION`, nieudany `prod-up` wycofuje na poprzedni commit i alarmuje
(`fingerprint=deploy-failed`), a nieudane wycofanie eskaluje do `fatal`. Kod wyjścia `1` w każdej
ścieżce błędu — bez tego CI świeciłoby na zielono przy zepsutej produkcji.

**Nie zweryfikowane i zweryfikowane być nie mogło:** przebieg na żywym VPS-ie (`make prod-build`
i `docker inspect` były atrapami) oraz to, czy `command=` w `authorized_keys` jest wpisane poprawnie —
procedura sprawdzenia jest w `docs/wdrozenie.md` §11.1 i jest to **pierwsza rzecz do zrobienia**
przed podłączeniem klucza do GitHuba.

### CI był czerwony od 2026-07-29 — naprawione 2026-08-06

Kroki 36, 37 i 39 zostały wypchnięte na czerwony pipeline i nikt tego nie zauważył. **Przyczyna:**
job `backend` robił `alembic upgrade head`, ale nigdy nie siał słownika rynków, a `assets.market_code`
ma FK na `markets` — każdy test tworzący aktywo kończył się `ForeignKeyViolation`. Ostatni przebieg
przed naprawą: **6 failed, 170 passed, 94 errors**, w tym **cała bramka izolacji dwóch użytkowników**
(94 błędy to wyłącznie `test_isolation.py`).

**Dlaczego nikt nie zauważył:** `make check` woła `docker compose exec api pytest`, czyli uderza
w bazę dev zasianą przez `make seed`. Lokalnie zielono, w CI czerwono — i to CI miało rację.
To ta sama klasa pułapki co „test przechodzi, ale niczego nie sprawdza": bramka izolacji, która
w CI wysypuje się na `ERROR` w fixture, nie sprawdza izolacji, a wygląda jak zwykły czerwony build.

**Skutek uboczny był poważniejszy niż sam kolor:** job `deploy` ma `needs: [backend, frontend,
obrazy-prod]`, więc CD nigdy by nie wystartowało — nawet po wgraniu wszystkich sekretów.

Naprawa: krok `Seed słownika rynków` (`python -m app.cli seed --reference-only`) między `Migracje`
a `Testy`. Odtworzone lokalnie na świeżej bazie (migracje bez seeda): 4 failed + 16 errors na samych
`test_meta_freshness` i `test_isolation`; po seedzie na tej samej bazie **251 passed, 3 deselected**.
Przebieg 31115157646 zielony w całości.

**Wdrożenie pomijane, dopóki brakuje sekretu.** Job `deploy` odpalał się przy każdym pushu na `main`
i padał na `ssh`. Teraz `DEPLOY_CONFIGURED` (`jobs.<id>.env`, bo kontekst `secrets` nie jest dostępny
w `jobs.<id>.if`) pilnuje `SSH_PRIVATE_KEY_ALPHASENSE` **i** `SSH_KNOWN_HOSTS`; przy braku któregoś
job kończy się zielony, wypisując `::notice::` i nie dotykając produkcji.
- [x] ~~**`SSH_KNOWN_HOSTS` to jedyny brakujący sekret wdrożeniowy**~~ — wgrany 2026-08-06, ale
  wdrożenie padało dalej: **klucz prywatny w `SSH_PRIVATE_KEY_ALPHASENSE` był uszkodzony**
  (`Load key "/home/runner/.ssh/id_ed25519": error in libcrypto` → `Permission denied (publickey)`,
  przebieg 31115680458 z 2026-08-07). Sekret wgrany ponownie przez użytkownika 2026-08-10 08:07.
  **Uwaga na przyszłość:** `error in libcrypto` to nie odrzucenie klucza przez serwer, tylko
  niepoprawny PEM po stronie runnera — zwykle obcięty nagłówek/stopka albo brak znaku nowej linii
  na końcu. Serwer nigdy tego klucza nie zobaczył, więc szukanie przyczyny w `authorized_keys`
  prowadzi w ślepy zaułek.

### `infra/deploy.sh` był w gicie bez bitu wykonywalności — naprawione 2026-08-10

Drugie wdrożenie z CI (przebieg 31374494720, commit `a1c9fa3`) padło z `exit code 126`:
`bash: /opt/alphasense/AlphaSense/infra/***.sh: Permission denied`. SSH uwierzytelnił się
poprawnie — nie wykonał się sam skrypt.

**Przyczyna:** `infra/deploy.sh` był zapisany w repo jako `100644`, choć lokalnie i na VPS-ie
miał `+x` nadany ręcznie po `git add`. Cztery skrypty backupu mają poprawne `100755` — ten
jeden wypadł z konwencji.

**Dlaczego pierwsze wdrożenie przeszło, a drugie nie:** `deploy.sh:222` robi
`git reset --hard "$TARGET_SHA"`, czyli przywraca tryby plików zapisane w repo. Pierwszy
przebieg wystartował z ręcznie nadanego `+x`, po czym **sam sobie ten bit odebrał**. Skrypt
wyłączył się przy pierwszym użyciu — awaria ujawniłaby się przy kolejnym wdrożeniu niezależnie
od tego, co by nim było.

Naprawa: `git update-index --chmod=+x infra/deploy.sh`. Od tego commita `reset --hard` sam
utrzymuje `755`. **Jednorazowo trzeba przerwać zakleszczenie na VPS-ie** (`chmod +x
/opt/alphasense/AlphaSense/infra/deploy.sh`) — wdrożenie nie może naprawić skryptu, którego
nie jest w stanie uruchomić.

## Pierwsze udane wdrożenie z CI — 2026-08-10

Przebieg 31115680458 (re-run zadania wdrożeniowego po naprawie sekretu): `Konfiguracja SSH` ✓,
**`Wdrożenie zatwierdzonego commita` ✓**. Produkcja podniesiona do `fd4946f` — `/api/health` zwraca
`{"status":"ok","db":"up","redis":"up","version":"fd4946f6f65d"}`, wcześniej ten endpoint dawał 404,
bo na VPS-ie stał obraz sprzed kroku 37. Ścieżka CD (GitHub → SSH → `deploy.sh` → `make prod-up`)
jest tym samym potwierdzona end-to-end.

**Nadal czerwony jest krok `Sprawdzenie z zewnątrz`** i to jest prawdziwa usterka produkcji, nie
szum w pipeline: Caddy serwuje **certyfikat ze stagingu Let's Encrypt** (`issuer=(STAGING)
Artificial Amaranth YE1`, wystawiony 2026-08-04), więc `curl` bez `-k` kończy się kodem 60
(`unable to get local issuer certificate`) na wszystkich 10 próbach. Ten sam endpoint z `-k`
odpowiada `ok`. **Kroku weryfikacyjnego nie rozluźniamy** — przeglądarka użytkownika ufa dokładnie
tak samo jak ten `curl`, a zielony deploy na niezaufanym certyfikacie byłby zielonym kłamstwem.

- [x] **Przełączenie na produkcyjne CA** — zrobione 2026-08-10. Certyfikat: `issuer=C = US,
  O = Let's Encrypt, CN = YE2` (bez `STAGING`), `subject=CN = alphasense.cedron.net.pl`,
  SAN `DNS:alphasense.cedron.net.pl`, ważny do 2026-11-08. `curl` bez `-k` zwraca
  `{"status":"ok","db":"up","redis":"up","version":"fd4946f6f65d"}`, `ssl_verify_result=0`.
  **Kosztowało to dwa nieudane podejścia i oba warto pamiętać:**
  1. Pierwsza próba przyniosła świeży, ale **wciąż stagingowy** certyfikat — w `.env.prod` było
     **drugie, niezakomentowane wystąpienie `ACME_CA=` niżej w pliku**, a w plikach env wygrywa
     ostatnie. Objaw jest zdradliwy: Caddy wypisuje `certificate obtained successfully` tak samo
     jak przy sukcesie, więc log nie odróżnia dobrego przebiegu od złego. Jedyne rozstrzygające
     sprawdzenie to `docker compose --env-file .env.prod -f docker-compose.prod.yml config
     | grep -i acme` **przed** restartem.
  2. `docker compose restart caddy` nie zobaczyłby zmiany w `.env.prod` — `restart` odpala ten sam
     kontener z wcześniej wstrzykniętym środowiskiem. Tylko `up -d` (`make prod-up`) go odtwarza.

  Runbook uzupełniony o oba punkty plus weryfikację z zewnątrz (`docs/wdrozenie.md` §4)
  i o ostrzeżenie przy samej zmiennej (`.env.prod.example`). Przy okazji sprostowane: kasowanie
  `/data/caddy/certificates` **nie jest** potrzebne przy zmianie CA — Caddy trzyma certyfikaty
  w podkatalogu nazwanym od hosta CA, więc po przełączeniu i tak nie znajdzie nic swojego.
- [x] **Smoke test na produkcji** — `E2E_BASE_URL=https://alphasense.cedron.net.pl make smoke`,
  2026-08-10: **2 passed** (`desktop` 6,0 s i `mobile-375` 7,3 s), pełna ścieżka rejestracja →
  portfel → pozycja → wartość → struktura % → ranking rynków. Wartość portfela wyszła niezerowa
  (`smoke.spec.ts:109` wymusza `/[1-9]/`), czyli produkcja ma realne ceny **i** kurs NBP — nie
  trzeba było ręcznego `python -m app.cli ingest --market CRYPTO` przewidzianego w §10 runbooka.
- [x] **Posprzątać konta smoke z produkcyjnej bazy** — zrobione 2026-08-10 przez użytkownika.
  Test zostawia `smoke-<znacznik>@alphasense.example` z portfelem i pozycją (dwa konta, po jednym
  na projekt Playwrighta); `DELETE FROM users WHERE email LIKE 'smoke-%@alphasense.example';`
  kaskaduje na jedno i drugie. **Powtarzaj po każdym smoke na produkcji** — procedura
  `docs/wdrozenie.md` §10.

## Backlog po code-review etapu 6 — DOMKNIĘTY 2026-07-29

Dwa **blokujące** znaleziska naprawione 2026-07-28 (patrz dziennik sesji). Pozostałe rozbrojone w sesji
2026-07-29, przed powrotem do etapu 7 — `make check` zielony (235 testów backendu, 29 Vitest, build),
Playwright 5/5.

- [x] **`price_change_1d` ignorowało `on_date`.** `marketdata/repository.get_latest_prices` dostało
  parametr `on_date` (filtr `date <= on_date`, ta sama reguła co `get_latest_price`), `portfolio/service.py`
  go przekazuje. `analytics.service._index_snapshot` zostaje bez filtra — ranking rynków z definicji pokazuje
  stan bieżący. Regresja: `test_price_change_1d_respects_historical_on_date` (notowania 20/40/50 na trzy
  kolejne dni, wycena na „wczoraj" musi dać 100%, nie 25%). Zweryfikowane, że test pada po cofnięciu poprawki.
  Likwidacja N+1 z oryginalnego wpisu **nie** zrobiona — to optymalizacja, nie błąd; osobny wpis niżej.
- [x] **Brak testu na rozdzielność klucza cache po `by`.** `test_allocation_cache_key_separates_dimensions`:
  `by=class` i `by=sector` na tym samym portfelu → dwa policzenia (`calls == 2`) i różne koszyki.
  Zweryfikowane, że test pada po usunięciu `by` z `cache_key(...)`.
- [x] **Kruchy `test_market_ranking_happy_path_with_index` i mutujący fixture `gpw_temp_index`** — naprawione
  razem, bo to był jeden problem: test opierał się na współdzielonym stanie. `gpw_temp_index` (podmieniał
  `Market("GPW").index_asset_id` i przywracał po teście) zastąpiony przez `ranking_markets`, który tworzy
  **dwa własne rynki**: jeden z indeksem i serią notowań, drugi z indeksem bez ani jednego wiersza `prices`.
  Przypadek `index: null` jest teraz wywołany warunkiem ustawionym przez test, a nie tym, czego worker EOD
  nie zdążył zaciągnąć — asercja nie padnie w dniu pierwszej udanej ingestii `^GSPC`. Fixture nie dotyka
  wiersza słownikowego, więc przestaje blokować zrównoleglenie testów.
- [x] **Vitest istnieje.** `frontend/vitest.config.ts` (`environment: "node"`, `include: lib/**/*.test.ts`),
  `npm run test`, dopięty do `make check` i do joba `frontend` w CI. 29 testów w czterech plikach:
  `lib/money.test.ts` (formatowanie kwot/procentów — asercje na semantyce, nie na dokładnym stringu z
  `Intl`, który zależy od wersji ICU), `lib/changeColor.test.ts` (trzy gałęzie znaku + obecność wariantu
  `dark:`), `lib/allocationLabels.test.ts` (`bucketLabel` z nieznanym kluczem, `toChartSlices` — sortowanie,
  składanie nadmiaru w „Pozostałe", suma wag = 1), `lib/topMovers.test.ts`.
  **Zakres świadomie bez jsdom i `@testing-library`**: nowe zależności to decyzja użytkownika (CLAUDE.md §10),
  a render pokrywa już Playwright przeciw żywemu stackowi. Logika wyboru top ruchów wyciągnięta z
  `components/dashboard/TopMovers.tsx` do `lib/topMovers.ts` (`splitTopMovers`), żeby dała się przetestować
  bez DOM-u — to jedyny refaktor w tej sesji i był warunkiem testowalności, nie porządkowaniem.
  Playwright **nadal poza `make check`** (wymaga żywego stacku) — do `make smoke` w kroku 39.
- [x] **Limit `POST /auth/login` ma zapas w devie.** `RATE_LIMIT_AUTH_PER_MINUTE=30` w `.env`/`.env.example`
  (dev/e2e), produkcja zostaje na `5`. Domyślna wartość w `core/config.py` bez zmian (`5`) — luz jest jawną
  decyzją środowiska deweloperskiego, nie nowym domyślnym zachowaniem. Odblokowuje pisanie osobnych plików
  e2e w kroku 39 zamiast doklejania scenariuszy do cudzych.
- [x] **`/dashboard` nie prowadzi już na 404.** `app/dashboard/{page,layout}.tsx` — `PortfolioPicker`
  z pustym `section` (nowy helper `targetHref`: pusty segment → `/portfolios/{id}`, czyli sam dashboard).
  Zachowanie identyczne z `/struktura` i `/rynki`: jeden portfel → `replace` prosto na widok, kilka → lista,
  zero → stan pusty z CTA. Zweryfikowane: `/dashboard` zwraca 200, `/nieistniejace` nadal 404.
- [x] **Nieaktualny odsyłacz do `foldBuckets`** w `lib/chartPalette.ts` → `toChartSlices`.
- [x] ~~`PortfolioDashboard.tsx:65` bez gałęzi `isLoading` dla `holdings`~~ — **wpis był nieaktualny**:
  szkielet ładowania dołożył krok 35 (commit `95f7d75`), już po napisaniu backlogu.

**Świadomie NIE zrobione w tej sesji** (i powód):
- Progi HHI `0.15`/`0.25` zaszyte w kodzie → `core/config.py` **przy etapie 8**, razem z resztą parametrów ryzyka.
- Deserializacja cache tworzy transientne obiekty ORM `Price` zamiast dataclassa — kosmetyka bez wpływu na wynik.
- `_range_start`/`_subtract_months` w trzech miejscach → `core/dates.py`: refaktor ponad zakres zadania
  (CLAUDE.md §4.3), nic dziś nie jest zepsute.
- N+1 w `_value_pairs` (`get_latest_price` + `get_latest_prices` per pozycja) — do zrobienia jednym zapytaniem,
  ale to optymalizacja, a nie błąd poprawności; naturalne miejsce to etap 8 razem z metrykami.


## Plan etapu 8 — metryki i ryzyko (uzgodniony 2026-08-06, przed rozpoczęciem)

Etap zaplanowany na sesji 2026-08-06 (`/etap 8`). **Nie zaczęty i zablokowany świadomie:**
decyzja 1 poniżej mówi, że najpierw domykamy etap 7 (wdrożenie na VPS + `make smoke` przez
produkcję). Praca CD została zacommitowana (`d203c14`) jako pierwszy element domykania.

**Decyzje użytkownika podjęte przy planowaniu:**

1. **Najpierw etap 7, potem etap 8.** Kroki 36-39 są zrobione w repo, ale Faza 1 nie została
   potwierdzona na produkcji ani razu. Zaczynanie etapu 8 wcześniej zwiększa dystans między tym,
   co przetestowane, a tym, co wdrożone (CLAUDE.md §5 „nie przeskakuj").
2. **Historia do metryk: backfill dev-only + fixture'y.** `make seed-history` odtworzy
   `portfolio_valuations` z historycznych cen **wyłącznie w devie/testach**, z jawnym blokiem na
   produkcji; testy jednostkowe na syntetycznych seriach o znanych liczbach. ADR-101 zostaje
   nienaruszone — produkcja nadal nie przelicza historii.
3. **Zakres pierwszej partii: kroki 40-42**, potem code-review i przegląd, dopiero wtedy decyzja
   o 43 (tagi/watchlisty), 44 (RLS) i 45 (świece).
4. **Benchmark przeliczany na PLN** kursem NBP, tak samo jak wycena portfela. Kurs walutowy jest
   częścią realnego wyniku inwestora; porównanie portfela w PLN z indeksem w USD mieszałoby dwie
   różne miary. Spójne z zasadą #5 (kursy wyłącznie z NBP).

**Decyzje dopisane 2026-08-10, przy starcie realizacji:**

5. **Backfill cen na 5 lat wstecz** (~1250 sesji). Daje zapas ponad próg 30 obserwacji, betę
   liczoną na więcej niż jednym epizodzie rynkowym i heatmapę miesięczną z realnym materiałem.
   **Konsekwencja do obsłużenia:** na takim horyzoncie splity przestają być teoretyczne (CDR, PKN),
   a zasada #4 wymaga liczenia na `close_adj`. Heurystyka z kroku 28 nigdy nie działała na tak
   długiej serii — weryfikacja na realnych danych jest częścią kroku zerowego, nie założeniem.
6. **Dziura w serii łączy łańcuch, z licznikiem pominiętych ogniw w odpowiedzi.** Weekend nie jest
   luką, tylko brakiem sesji, a zrywanie ogniwa przy każdej dziurze wycinałoby przy nieregularnym
   workerze większość okresu i **zaniżało zwrot bez ostrzeżenia**. Licznik jest tu istotny: bez
   niego „zwrot za 1Y policzony z 40 ogniw" wygląda identycznie jak policzony z 250.
   Zrywa wyłącznie `composition_change=true`.
7. **Zakres startu: krok zerowy → 40 → 42 → 41**, zgodnie z decyzją 3.

**Stan wyjściowy (zweryfikowany na żywej bazie dev 2026-08-06):**

```
portfolio_valuations:  0 wierszy (żaden portfel, żadna data)
^GSPC (S&P 500):       0 notowań
WIG20:                 2 notowania (2026-07-30 … 08-03)
^GDAXI/^FCHI/^FTSE/^SSMI: po 8 notowań (2026-07-22 … 08-03)
^HSI/^NDX/^N225:       0 notowań
```

Kroki 40-42 są w całości funkcjami szeregu czasowego, którego dziś **nie ma**. Stąd decyzja 2
i „krok zerowy" (dane) przed krokiem 40.

**Krok zerowy — stan faktyczny zweryfikowany 2026-08-10 (zakres mniejszy, niż zakładał plan)**

Dwa z czterech elementów **już istnieją** — praca z kroku 37 wyprzedziła ten plan:
`SourceMapSeed("WIG20", "GPW", "yfinance", "WIG20.WA", 2)` i
`SourceMapSeed("^GSPC", "US", "yfinance", "^GSPC", 1)` (`backend/app/db/seed.py:238,244`),
oba potwierdzone w bazie dev. Zostaje więc `backfill-prices` i `make seed-history`.

Baza dev na 2026-08-10: `portfolio_valuations` **0 wierszy**, `^GSPC` 0 notowań, `WIG20` 2,
`^GDAXI` 8, `CDR`/`PKN` po 10, `bitcoin` 12 (seria stoi od 2026-07-24 — worker dev nie chodzi).
Najdłuższa seria ma 12 punktów przy progu 30 obserwacji, więc dziś każda metryka ryzyka
zwróciłaby `null`. Krok zerowy jest ścieżką krytyczną etapu, nie dodatkiem.

**`seed-history` reużywa `snapshot_portfolios(run_date)`**, zamiast implementować drugą ścieżkę
wyceny — druga rozjechałaby się z produkcyjną przy pierwszej zmianie w `current_value`.

**Historia z `seed-history` jest SYNTETYCZNA i tylko tak wolno ją opisywać.**
`snapshot_portfolios.py:83-84` wycenia portfel w **dzisiejszym** składzie cenami z podanego dnia,
a `composition_change` bierze z `portfolio.holdings_changed_at == effective_date`. Pętla po
przeszłości daje więc „ile byłby wart dzisiejszy skład 5 lat temu", nie „ile portfel był wart"
(ADR-101 — aplikacja z definicji nie zna tej historii). Wniosek praktyczny: `composition_change`
wyjdzie prawie wszędzie `false`, więc **ta historia nie przećwiczy sedna kroku 40** (zrywania
ogniwa). Backfill daje objętość dla metryk ryzyka; poprawność łańcucha muszą pokryć testy
jednostkowe na syntetycznych seriach o znanych liczbach.

**Krok zerowy — co powstało i co znalazły pierwsze przebiegi (2026-08-10)**

Narzędzia: `backfill_prices()` + `_date_chunks()` w `worker/jobs/ingest_market.py`,
komendy CLI `backfill-prices` i `seed-history`, cele `make backfill` / `make seed-history`
(parametry `years=`/`from=`), liczniki `count_prices_in_range` / `count_fx_rates_in_range`
w `marketdata/repository.py`. `ruff` i `mypy` czyste. **Testów jeszcze nie ma — krok zerowy
NIE jest domknięty.**

Trzy rzeczy wyszły dopiero na żywych danych:

1. **API NBP odrzuca zakresy > 367 dni**, a `nbp.py:53` wkleja zakres prosto w URL. Pięcioletni
   backfill kursów padłby na pierwszym zapytaniu — kursy są potrzebne, bo `^GSPC` jest w USD,
   a decyzja 4 każe pokazywać benchmark w PLN. Dzielenie na okna po 365 dni siedzi w warstwie
   backfillu, **nie w dostawcy**: kontrakt `DataProvider` brzmi „daj mi ten zakres", a pętla
   w `NbpProvider` dotknęłaby też codziennej ingestii (okna po `_LOOKBACK_DAYS`).
2. **Pierwsza wersja licznika kłamała.** `_ingest_asset_ohlcv` zwraca nazwę dostawcy także wtedy,
   gdy `bars` było puste, więc raport pokazał „WIG20: 5 okien" przy jednym wierszu w bazie.
   Licznik przepisany na **wiersze w bazie** (`count_prices_in_range`). Ta sama klasa błędu co
   „test przechodzi, ale niczego nie sprawdza" — raport wyglądał na sukces i nim nie był.
3. **WIG20 nie ma dziś działającego źródła historii.** Stooq zwraca **404** na
   `https://stooq.pl/q/d/l/?s=cdr&d1=20250810&d2=20260810&i=d` (sprawdzone na CDR; po pięciu
   porażkach `CircuitBreaker` otworzył obwód — poprawnie, stan w Redisie z TTL 30 dni),
   a yfinance odpowiada `$WIG20.WA: possibly delisted; no price data found` na każdym oknie.
   Akcje GPW ratuje yfinance: **CDR → 248 notowań za rok** (~252 sesje, bez weekendów).
   **Rozstrzygnięte tego samego dnia — bez nowego dostawcy.** Diagnoza poszła dalej:
   Stooq zwraca **200 ze stroną HTML 796 B** (`robots: noindex,nofollow`, wyzwanie anty-bot
   opisane w skillu `data-provider`) na każdy symbol i obie domeny — nie 404, jak wyglądało
   z kontenera. Yahoo **zna** `WIG20.WA` jako indeks WSE, ale endpoint wykresu oddaje
   **dokładnie jeden punkt** (dzisiejszy) zamiast serii; to samo `WIG20TR.WA`. Czyli nie
   był to nasz błąd w budowaniu zapytania.

   **Decyzja użytkownika 8 (2026-08-10): benchmarkiem GPW jest `ETFBW20TR.WA`** — ETF Beta
   WIG20TR notowany na GPW, **1251 punktów za pięć lat przez yfinance**, którego już używamy.
   Zero nowych zależności (CLAUDE.md §10). Kompromisy do pokazania w UI: ETF śledzi WIG20
   **Total Return** (z dywidendami), nie indeks cenowy — wobec portfela, który dywidendy
   otrzymuje, jest to miara uczciwsza, nie gorsza; dochodzi błąd odwzorowania i opłata za
   zarządzanie rzędu 0,5% rocznie. Notowany w PLN, więc dla tego benchmarku przeliczenie
   kursem NBP (decyzja 4) jest tożsamościowe.

   Wpisany jako **`BENCHMARK_ASSETS`, osobno od `INDEX_ASSETS`** (`app/db/seed.py`): tamta
   krotka jest mapowana per rynek i dowiązywana do `markets.index_asset_id`, więc dopisanie
   drugiego aktywa GPW po cichu podmieniłoby indeks referencyjny rynku i zmieniło panel
   „Twoje rynki" z kroku 34. Zweryfikowane po seedzie: `GPW → WIG20`, `US → ^GSPC` bez zmian.
   `_seed_reference` zwraca teraz dwie mapy (indeksy per rynek, benchmarki per symbol),
   a `seed_reference` sieje mapowania benchmarków także na produkcję — bez nich krok 42
   nie miałby czym zaciągnąć serii porównawczej.

**Stan po backfillach (2026-08-10):** `^GSPC` **1254**, `ETFBW20TR` **1250**, `CDR` 248 notowań
za pięć lat. Oba benchmarki kroku 42 mają komplet historii.

Stan `prices` po przebiegach próbnych: `CDR` 248 (2025-08-11 .. 2026-08-10), `WIG20` 3,
`^GSPC` 0 (rynek `US` jeszcze nie ruszany), `PKN` 10, `bitcoin` 12.

**Krok zerowy — dane** (`data-provider`)
Fallback yfinance dla `WIG20` w `asset_source_map` (wpis z backlogu etapu 4 przestaje być
nieblokujący) · mapowanie dostawcy dla `^GSPC` · jednorazowe `python -m app.cli backfill-prices
--symbol … --from …` (Stooq/yfinance oddają lata historii) · `make seed-history` z decyzji 2.
**To dodatek ponad plan** — bez niego kroki 42 i 41 (beta) nie mają czego liczyć.

**Krok 40 — zwroty dzienne ze snapshotów** (`analityka` + `qa-testy`)
`backend/app/modules/analytics/returns.py` (czyste funkcje na `Decimal`: `daily_returns`,
`chain_link`, `period_return`) · `GET /portfolios/{id}/performance?range=1M|3M|1Y|YTD|max` ·
cache Redis kluczem wersjonowanym jak w kroku 31 · aktualizacja `docs/api-kontrakt.md` ·
testy jednostkowe na znanych liczbach, bez mocków bazy.
**Sedno:** dzień z `composition_change=true` **zrywa ogniwo** łańcucha (zwrot z t-1 na t wypada),
a nie kasuje obu dni — inaczej dokupienie udawałoby zysk (ADR-101). Zwrot okresowy = iloczyn
zachowanych ogniw. **Do rozstrzygnięcia w kodzie:** dziura w serii (weekend, brak snapshotu) —
propozycja: łączy przez przerwę, z liczbą pominiętych ogniw w odpowiedzi.

**Krok 42 — benchmark** (`data-provider` → `analityka` → `frontend-next`)
**Przesunięty przed krok 41**, bo beta potrzebuje serii benchmarku. Rozszerzenie
`/performance?benchmark=WIG20|^GSPC` o drugą serię znormalizowaną do 100 (obie przeliczone na PLN,
decyzja 4) · wykres na widoku wyników.

**Krok 41 — ryzyko** (`analityka` + `frontend-next`)
`analytics/risk.py` (zmienność = odch. std × √252, Sharpe, max drawdown, seria underwater, beta,
zwroty miesięczne) · `GET /portfolios/{id}/risk?range=&benchmark=` · widok ryzyka: karty metryk
z interpretacją słowną, wykres underwater, heatmapa miesięczna.
**Sedno:** drawdown liczony na **indeksie łańcuchowym**, nie na `value_pln` — inaczej wpłata
wygląda jak wyjście z obsunięcia. **Reguła minimalnej próby:** poniżej 30 obserwacji metryka
zwraca `null` + powód („21 z 30 wymaganych dni"), a UI pokazuje to zamiast liczby — ta sama
zasada co „nie licz jako zero, wyklucz z mianownika" z kroku 34.
**Stopa wolna od ryzyka:** parametr `RISK_FREE_RATE_ANNUAL` w `pydantic-settings` z domyślną
wartością stopy referencyjnej NBP i datą w komentarzu. Pobieranie jej z API NBP to nowy dostawca
(CLAUDE.md §10) — nieproporcjonalne do jednej liczby zmienianej kilka razy w roku.

**Kroki 43-45 — poza pierwszą partią** (decyzja 3), rozpoznane przy planowaniu:
- **43 (tagi/watchlisty):** tabele `watchlists`/`watchlist_items`/`tags`/`asset_tags` nie mają
  w `docs/model-danych.md` zdefiniowanych kolumn („Faza 2") — schemat do zaprojektowania. Tagi
  **per użytkownik** (`tags.user_id`, `UNIQUE(user_id, lower(name))`), nie globalne. Do
  sprawdzenia, czy parametryzowany harness izolacji łapie parametry `tag_id`/`watchlist_id`.
  Pilnowanie zakresu: watchlista = lista aktywów z notatką, nie „portfel papierowy" (§1).
- **44 (RLS):** najbardziej ryzykowny krok etapu. `SET LOCAL app.user_id` działa tylko wewnątrz
  transakcji, a pula połączeń async SQLAlchemy może przenieść ustawienie między żądaniami.
  Do rozstrzygnięcia, czy `users`/`refresh_tokens` w ogóle dostają polityki — rejestracja
  i logowanie dzieją się, zanim istnieje `user_id`. Kolejność: **po** 43 (nowe tabele od razu
  z politykami) i po zweryfikowanym backupie.
- **45 (świece):** napięcie z zasadą #4 — w `prices` mamy surowe OHLC i skorygowany wyłącznie
  `close`. Propozycja: skalować OHLC współczynnikiem `close_adj/close` i udokumentować.
  Pierwszy realny konsument `GET /markets/{code}/index` (dziś bez konsumenta, backlog kroku 34).

**Zależności:** `dane → 40 → 42 → 41`; `43 → 44`; `45` dzieli z 42 wymóg historii notowań.
43 jest niezależne od 40-42.

**Ryzyka do pilnowania przy realizacji:**
- Zero snapshotów i puste serie indeksów — adresowane decyzją 2 i krokiem zerowym.
- Pełzanie zakresu ku transakcjom/XIRR/przepływom (§1) — wszystko liczone z serii cen,
  `/kontrola-zakresu` po kroku 41.
- Sharpe/zmienność na krótkiej próbie to szum — próg 30 obserwacji, `null` z powodem.
- RLS (krok 44) może zablokować aplikację na produkcji — gotowa migracja wstecz, test „sesja bez
  `app.user_id` widzi 0 wierszy", wdrożenie po zweryfikowanym backupie.

**Kryterium ukończenia pierwszej partii (40-42):** na portfelu z historią co najmniej trzech
miesięcy widzisz zwrot za okres liczony z pominięciem dni zmiany składu, zmienność, Sharpe'a,
max drawdown i betę (albo jawny komunikat o zbyt krótkiej próbie), wykres underwater, heatmapę
miesięczną oraz przebieg portfela na tle WIG20 lub S&P 500 znormalizowany do 100 (obie serie
w PLN). `make check` zielony, `docker compose up` wstaje.

## Krok 41a — źródło stopy referencyjnej NBP (ZROBIONY 2026-08-25)

Podkrok kroku 41: Sharpe potrzebuje stopy wolnej od ryzyka, a plan mówi „stopa
referencyjna NBP jako konfigurowalny parametr". **Decyzja użytkownika (2026-08-25):
pobieramy ją z rzeczywistego źródła, historycznie**, a nie jako stałą w ENV — Sharpe
na wieloletniej serii ze stałą dzisiejszą stopą byłby policzony źle (stopa szła w tym
okresie od 0,10% do 6,75%). Wariant `RISK_FREE_RATE` w ENV odpadł.

**Źródło (ustalone na żywo, nie z dokumentacji):** `api.nbp.pl` — ten sam, z którego
bierzemy kursy i złoto — **nie wystawia stóp procentowych** (`/api/interestrates` → 404).
NBP publikuje je jako statyczne pliki XML na `static.nbp.pl`:
`stopy_procentowe.xml` (stan bieżący) i `stopy_procentowe_archiwum.xml`
(**pełna historia od 1998-02-26**, 96 zmian). Bierzemy **wyłącznie archiwum** — jego
ostatni wpis jest identyczny z plikiem bieżącym (test pilnuje tego założenia), więc
drugie żądanie byłoby kolejnym punktem awarii bez żadnego zysku.

**Pułapka udokumentowana w kodzie i w teście:** atrybut `data_publikacji` w archiwum
stoi na `2015-03-04`, mimo że treść sięga 2026-03-05 — NBP go nie aktualizuje.
Świeżość liczymy wyłącznie z `max(effective_from)`.

**Co powstało:**
- `backend/app/modules/marketdata/providers/nbp_rates.py` — `ReferenceRate`,
  `NbpReferenceRatesProvider`, `GuardedReferenceRates` (limiter + bezpiecznik; przy
  dywidendach tego zabrakło i było znaleziskiem recenzji, tu nie powtórzone).
  Świadomie **poza** `Protocol DataProvider`: stopa procentowa to nie `Capability.FX`
  ani `OHLCV`, więc nie wchodzi do `FallbackChain`.
- Tabela `nbp_reference_rates` (migracja `7a1c4e2b9f38`), model `NbpReferenceRate`.
  Wiersz = zmiana stopy, PK jednokolumnowy, `rate` jako **ułamek roczny**
  (`0.03750000`), nie procent.
- `repository.upsert_reference_rates` / `get_reference_rate` (lookup
  `max(effective_from) <= D`, jak przy kursach) / `list_reference_rates`
  (dociąga wpis sprzed `start`, żeby początek serii nie został bez stopy) /
  `get_latest_reference_rate_date`.
- `backend/worker/jobs/ingest_nbp_rates.py` — job **tygodniowy** (środa 6:20 UTC,
  `CronTrigger`), blokada doradcza `ingest_nbp_rates`, jedno żądanie o pełne archiwum,
  `ON CONFLICT DO UPDATE`. Nieudany przebieg **nie** rzuca: poprzednie wartości są nadal
  poprawne (stopa obowiązuje do następnej decyzji RPP), więc awaria źródła co najwyżej
  opóźnia zauważenie zmiany o tydzień.
- `docs/model-danych.md` — wiersz tabeli + uzasadnienia.

**Decyzje projektowe:**
- Zapisujemy **tylko stopę referencyjną** (`ref`), nie wszystkich pięciu z XML-a —
  pozostałe nie mają w projekcie odbiorcy (CLAUDE.md #3.11).
- Parsowanie stdlib `xml.etree.ElementTree` + twardy limit 4 MB na odpowiedź,
  **bez** dokładania `defusedxml` (nowa zależność wymagałaby osobnej decyzji,
  CLAUDE.md #10). ElementTree w CPythonie nie rozwiązuje encji zewnętrznych, więc
  limit rozmiaru zamyka realne ryzyko („billion laughs").
- Brak stopy dla danej daty → `None`, **nigdy zero**: zero jest poprawną stopą
  (RPP miała 0,10%), więc podstawione cicho zmieniłoby Sharpe'a nie do odróżnienia
  od policzonego na prawdziwych danych. Krok 41b ma wtedy **nie liczyć** wskaźnika.

**Weryfikacja:** 17 nowych testów (7 jednostkowych na parserze + nagranych fixture'ach
`stopy_archiwum.xml`/`stopy_biezace.xml`, 2 na samych fixture'ach, 8 integracyjnych na
lookupie i idempotencji). Cała suita **459 passed** (było 442). `ruff format --check`,
`ruff check`, `mypy app worker`, `next build` — zielone. `alembic heads` → jedna głowa
`7a1c4e2b9f38`. Job uruchomiony na żywo: 96 wierszy zapisanych, `latest=2026-03-05`.
Lookup sprawdzony na realnych datach: 2026-08-25 → 3,75%, 2023-09-06 → 6,75%,
2020-05-29 → 0,10%, 1990-01-01 → `None`. Scheduler po restarcie rejestruje
`ingest_nbp_rates` (16 jobów).

**Nie zrobione (świadomie, to krok 41b):** żadnej metryki ryzyka jeszcze nie ma —
`nbp_reference_rates` nie ma na razie ani jednego konsumenta poza testami, tabela
czeka na Sharpe'a. Świeżość tej serii nie jest jeszcze pokazana w `/meta/freshness`.

## Krok 45 — wykresy świecowe (ZROBIONY 2026-08-26) — KONIEC ETAPU 8

`GET /assets/{asset_id}/candles?range=`, `marketdata/candles.py`, komponenty
`CandleChart`/`CandlePanel` na Lightweight Charts, trasa `/assets/[id]`.

### Sedno: napięcie z zasadą CLAUDE.md #4, zapowiedziane przy planowaniu etapu

`prices` trzyma **surowe** OHLC i skorygowany wyłącznie `close_adj` — dostawcy oddają
OHLC w cenach z dnia notowania. Narysowanie świec wprost z tych kolumn złamałoby zasadę
„wykresy zawsze na `close_adj`" w najbardziej mylący sposób: knoty i korpusy sprzed splitu
wisiałyby kilka razy wyżej niż linia zamknięcia, którą użytkownik zna z wykresu wartości
portfela. Rozstrzygnięcie zgodne z propozycją z planu: **cała świeca skalowana
współczynnikiem `close_adj / close`** z tego samego dnia. Split i dywidenda przeskalowują
cały dzień, nie samo zamknięcie, więc kształt świecy zostaje nietknięty — zmienia się
poziom. Dla serii bez korekt (Stooq/Finnhub/Binance wpisują `close_adj := close`)
współczynnik wynosi dokładnie 1 i wynik jest identyczny z surowym OHLC.

### Pozostałe decyzje

- **`close` bierzemy wprost z `close_adj`**, nie z `close * współczynnik` — matematycznie
  to samo, ale bez błędu zaokrąglenia mnożenia i dzielenia. To jest liczba, którą
  użytkownik widzi też w wycenie pozycji, więc musi zgadzać się co do grosza.
- **`volume` bez skalowania** — to sztuki, nie cena; skalowanie wolumenu współczynnikiem
  cenowym byłoby osobną decyzją, nie efektem ubocznym korekty cen. W kontrakcie zostaje
  liczbą, nie stringiem (nie jest kwotą, więc CLAUDE.md #3.1 go nie dotyczy).
- **Niekompletna sesja wypada z serii i jest POLICZONA** (`skipped` w odpowiedzi).
  Wiersz bez kompletu OHLC nie daje się skorygować, a domalowanie świecy z `close_adj`
  w każdym rogu byłoby wymyślaniem danych. Wykres z dziurą wygląda dokładnie jak
  kompletny, więc liczba musi dojechać do UI (CLAUDE.md #3.15) — panel pokazuje ją
  zdaniem nad wykresem.
- **Jedna trasa na aktywo i indeks.** Bliźniacze `/markets/{code}/candles` napisałem
  i **usunąłem**: indeks referencyjny jest zwykłym aktywem (ADR-102), a panel „Twoje
  rynki" zna jego `asset_id`, więc druga trasa byłaby endpointem bez konsumenta —
  dokładnie tym, co przy kroku 34 zostało zapisane w backlogu jako zapach.
- **Lightweight Charts, nie ECharts** — podział wprost z CLAUDE.md §2. Powód praktyczny:
  przewijanie i skalowanie osi czasu na dotyku, czyli to, po co ogląda się świece,
  jest tu wbudowane. Dynamiczny `import()` w `useEffect`, jak `EChart` z kroku 33.
- **`/assets/[id]` to sam wykres.** Wskaźniki fundamentalne i techniczne to **Etap 10**
  planu v3 (Single Asset Analysis) — dokładanie ich tutaj byłoby wejściem w zakres,
  którego v2 nie obejmuje. Wejścia: symbol pozycji w panelu tagów, symbol na watchliście,
  link „Zobacz świece {indeks} →" w panelu rynków.
- **Kwoty jako string aż do granicy rysowania.** `toChartCandles` zamienia je na `number`
  wyłącznie dla biblioteki wykresu — na wykresie utrata cyfr znaczących jest niewidoczna,
  w liczbie na ekranie byłaby błędem.

### Weryfikacja

- `tests/unit/test_candles.py` (7) — na ręcznie policzonych liczbach: split 2:1 skaluje
  całą świecę i **zachowuje jej proporcje**, zamknięcie idzie z `close_adj`, wolumen bez
  zmian, niekompletny wiersz i `close <= 0` wypadają i są policzone.
- `tests/integration/test_candles.py` (5) — kontrakt: stringi, korekta zastosowana,
  `skipped` w odpowiedzi, rosnąco po dacie, 404/422.
- `lib/candles.test.ts` (5) — konwersja do wykresu i polska odmiana „sesja" po liczebniku.
- **Żywa weryfikacja na dev:** AAPL 2026-08-06, wiersz z realną korektą dywidendową
  (`close=312.41000366`, `close_adj=312.14080811`): endpoint zwrócił
  `open=314.06913777` — zgodnie z ręcznym przeliczeniem `314.33999634 × 0.99913833`
  co do ósmego miejsca. MSFT `range=1M`: 12 świec, `skipped=0`.
- Backend **560 passed**, frontend: lint, `tsc`, Vitest **89 passed**, `next build`
  z trasą `/assets/[id]`.

### Zostaje po kroku 45 (nieblokujące)

- **Brak wolumenu na wykresie** — dane są w odpowiedzi, ale panel ich nie rysuje
  (osobna seria histogramu pod świecami to naturalne rozszerzenie).
- **Brak wskaźników technicznych** (MA50/MA200, RSI) — świadomie: to Etap 10 planu v3.
- **`/assets/[id]` nie pokazuje pozycji użytkownika w tym aktywie** (ilość, wynik) —
  ekran jest czysto rynkowy; powiązanie z portfelem wymagałoby decyzji, czy to już
  Single Asset Analysis.
- **Trasa wymaga zalogowania, choć endpoint jest publiczny** — decyzja produktowa
  (wchodzi się tu z portfela), ale to niespójność warta odnotowania.
- Świece nie mają cache Redis, w odróżnieniu od analityki portfela — seria cen jest
  tania, ale przy szerokim `range=max` na ruchliwym instrumencie warto zmierzyć.

## Krok 44 — Row Level Security (ZROBIONY 2026-08-26)

Domknięcie ADR-002: trzecia warstwa izolacji danych. Migracja `8d1f2a6c40b7`,
`app/db/rls.py`, rozdzielenie ról bazy, `make db-roles`, `tests/integration/test_rls.py`.

**Co realnie chroni:** 7 polityk na `portfolios`, `holdings`, `portfolio_valuations`,
`tags`, `asset_tags`, `watchlists`, `watchlist_items`. Trzy pierwsze i `tags`/`watchlists`
po `user_id`, tabele bez tej kolumny — przez rodzica (`portfolio_id IN (SELECT id FROM
portfolios)`), przy czym podzapytanie samo podlega polityce rodzica.

### Decyzje, które okazały się sednem tego kroku

- **Dwie role bazy, nie jedna.** To jest cała różnica między RLS działającym a RLS
  udawanym: **właściciel tabeli i superużytkownik omijają polityki milcząco**. Aplikacja
  łączona dotychczasową rolą `portfel` (superużytkownik!) przeszłaby całą suitę zieloną,
  nie mając włączonej ochrony. Stąd `portfel_app` (`DATABASE_URL_APP`) bez `BYPASSRLS`
  i bez własności tabel, a `tests/integration/test_rls.py::test_rola_aplikacji_nie_omija_polityk`
  pilnuje właśnie tego — pada pierwszy, jeśli konfiguracja kiedyś wróci do jednej roli.
- **`SET LOCAL` przy KAŻDEJ transakcji, nie raz na sesję.** Zwykłe `SET` przeżywa zwrot
  połączenia do puli, więc następne żądanie odziedziczyłoby cudze `app.user_id` — czyli
  dokładnie ten wyciek, przed którym RLS broni. Ale `SET LOCAL` żyje tylko do `COMMIT`,
  a jedno żądanie robi kilka transakcji (serwisy commitują same), więc ustawienie raz
  w `get_db` znikałoby po pierwszym commicie i reszta żądania widziałaby zero wierszy.
  Rozwiązanie: listener na zdarzeniu `begin` silnika + `ContextVar` per żądanie
  (`app/db/rls.py`), plus jawny `set_config` w `get_current_user` dla transakcji,
  która akurat już trwa.
- **Brak kontekstu = zero wierszy**, nie „wszystko": `NULLIF(current_setting(...), '')::uuid`
  daje `NULL`. To jest kryterium akceptacyjne z planu etapu 8 i osobny test.
- **`users` i `refresh_tokens` bez polityk** — rejestracja, logowanie i rotacja tokenu
  dzieją się, **zanim** istnieje `app.user_id`; polityka zablokowałaby własne
  uwierzytelnianie. Ochrona tych tabel zostaje na warstwie 1 (ADR-002).
- **Worker i CLI na `OwnerSessionLocal`, nie na zmiennej środowiskowej.** Pierwsze podejście
  (worker bez `DATABASE_URL_APP`) działało w kontenerze, ale wywaliło 5 testów jobu
  snapshotów uruchamianego w procesie testowym: job widział `portfolios_total=0` zamiast
  błędu. Joby dostały więc jawną sesję właściciela — „potrzebuję pełnej bazy" ma być
  widoczne w kodzie, a nie zależne od tego, który kontener dostał którą zmienną.
- **Hasło roli nie trafia do migracji**, bo migracje są w repo (CLAUDE.md #3.9). Migracja
  tworzy rolę bez `LOGIN`, `python -m app.cli db-roles` (`make db-roles`) nadaje hasło
  z `DATABASE_URL_APP`. `ALTER ROLE ... PASSWORD` nie przyjmuje parametru wiązanego, więc
  cytowanie zleca się Postgresowi (`format('%I ... %L')`), zamiast sklejać hasło f-stringiem.
- **Tryb awaryjny to „bez RLS", nie „500".** Pusty `DATABASE_URL_APP` = połączenie rolą
  właściciela: aplikacja działa, ochrony nie ma, a `deploy.sh` krzyczy ostrzeżeniem w logu.
  Świadomy kompromis: wdrożenie, które gubi jedną zmienną, nie ma kłaść produkcji.

### Weryfikacja

- `alembic downgrade -1` → 0 polityk, `upgrade head` → 7 polityk (sprawdzone na żywo,
  wymagane planem etapu 8: „gotowa migracja wstecz").
- `tests/integration/test_rls.py` — 5 testów: rola nie omija polityk, sesja bez
  `app.user_id` widzi zero wierszy (także po znanym ID), kontekst pokazuje tylko swoje
  wiersze, dziedziczenie właściciela po rodzicu, brak przecieku kontekstu między sesjami
  z tej samej puli.
- **Cała suita integracyjna jedzie teraz przez RLS naprawdę** — `_override_get_db` używa
  roli aplikacji, a `db_session` (setup/sprzątanie) roli właściciela. Backend **548 passed**.
- `docker compose up` wstaje w komplecie, `/api/health` `db: up` na roli aplikacji, worker
  wykonuje joby na roli właściciela.

### Zostaje po kroku 44 (nieblokujące)

- **`FORCE ROW LEVEL SECURITY` nie jest włączone** — właściciel nadal omija polityki, co
  jest tu funkcją (worker, migracje), ale znaczy też, że pomyłkowe połączenie API rolą
  właściciela nie zostanie zauważone przez bazę, tylko przez test.
- **Brak polityk na `users`/`refresh_tokens`** (uzasadnienie wyżej) — do rozważenia
  osobna polityka „tylko własny wiersz" dla odczytów po zalogowaniu.
- **`DATABASE_URL_APP` nie jest wymagane przez konfigurację** — pusty string jest legalny
  i daje cichy tryb bez RLS. Do rozważenia twarda walidacja przy `ENV=prod`.
- Nowe tabele w przyszłych migracjach **nie dostaną polityk automatycznie**; `ALTER DEFAULT
  PRIVILEGES` załatwia tylko nadania. Warto dopisać to do skilla `migracja`.

## Krok 43 — watchlisty i tagi (ZROBIONY 2026-08-26)

Podzielony na **43a** (backend) i **43b** (frontend). Backend powstał 2026-08-25
(w połowie, suita czerwona), dokończony razem z frontendem 2026-08-26.

**43a — backend:**
- Cztery tabele + migracja `f76793e14dad` (zastosowana, jedna głowa):
  `watchlists`, `watchlist_items`, `tags`, `asset_tags`. Klucze złożone z par
  naturalnych, FK do `assets` bez kaskady (jak `holdings.asset_id`), kaskada
  z `users` w dół. Modele zarejestrowane w `alembic/env.py`.
- `core/deps.py`: `get_owned_watchlist`/`WatchlistDep` i `get_owned_tag`/`TagDep`
  — wzorzec 404-zawsze, filtr własności w zapytaniu.
- Moduł `modules/tags/` (models, repository, schemas, service, routes):
  `GET/POST /tags`, `PATCH/DELETE /tags/{tag_id}`, `GET /tags/{tag_id}/assets`,
  `PUT/DELETE /tags/{tag_id}/assets/{asset_id}`.
- Moduł `modules/watchlist/` (jw.): `GET/POST /watchlists`,
  `PATCH/DELETE /watchlists/{watchlist_id}`, `GET /watchlists/{watchlist_id}/items`,
  `PUT/DELETE /watchlists/{watchlist_id}/items/{asset_id}`.
- Oba routery wpięte w `app/main.py`. `ruff`, `mypy` — zielone.

**Decyzje projektowe (podjęte i zapisane w kodzie):**
- **Tag wisi na AKTYWIE, nie na pozycji** — tak rezerwuje `docs/model-danych.md`
  (`asset_tags`) i tak jest użyteczniej: „dywidendowe" to cecha spółki, więc tag
  działa we wszystkich portfelach użytkownika.
- **Tag należy do użytkownika, `assets` jest globalne** — izolacja przy każdym
  odczycie idzie przez `JOIN tags` po `tags.user_id`. Bez tego użytkownik A
  zobaczyłby, że ktoś oznaczył PKN jako „do sprzedania".
- **Chronionym zasobem jest tag, nie aktywo** — stąd `/tags/{tag_id}/assets/{asset_id}`,
  a nie odwrotnie.
- **Filtr `?tags=` ma mieć semantykę OR (suma), nie AND** — przecięcie dla
  większości par tagów dałoby pustkę i wyglądało jak awaria filtra. Zapisane
  w `tags/repository.asset_ids_for_tag_names`.
- **Watchlista to nie portfel** — bez ilości, wyceny, snapshotów i analityki
  (CLAUDE.md #3.11). `WatchlistItemOut` świadomie nie ma `value_pln`.
- `PUT` (idempotentny) zamiast `POST` dla wiązania; `DELETE` zwraca 204 także
  gdy powiązania nie było.
- Duplikat nazwy → `ConflictError` (409) z komunikatem po polsku; `UNIQUE`
  w bazie zostaje jako ostatnia linia obrony.

**Dokończone 2026-08-26 (43a):**
1. **Czerwona suita naprawiona.** Harness `tests/test_isolation.py` sam wykrył nowe
   trasy i padał `KeyError: 'tag_id'`/`'watchlist_id'` — **luka w fixture, nie
   wyciek** (`get_owned_tag`/`get_owned_watchlist` były wpięte wszędzie). Fixture
   tworzy teraz użytkownikowi A tag i listę, a do `ids` doszedł **`asset_id`**:
   ścieżki wiążące (`/tags/{tag_id}/assets/{asset_id}`) mają w URL-u drugi
   identyfikator, który nie jest zasobem chronionym, ale musi być czym wypełnić.
   Wpisane jest **realne** aktywo — losowy UUID dawałby 404 z powodu nieistniejącego
   aktywa, czyli test przechodziłby nie sprawdzając nic o własności tagu.
   Harness pokrywa dziś **10 tras** tagów i watchlist automatycznie.
2. **Filtr `?tags=` w `GET /portfolios/{id}/allocation`.** Zawęża pozycje **przed**
   policzeniem wag — wagi sumują się do 100% w obrębie tego, co filtr przepuścił
   („jak wygląda struktura mojej części dywidendowej"), a nie „jaki udział w całości
   ma część dywidendowa". Semantyka OR. Segment `tags=` jest w kluczu cache
   **zawsze**, także bez filtra (`tags=-`): gdyby pojawiał się tylko przy filtrze,
   zapytanie z `?tags=` trafiałoby w klucz zapytania bez filtra. Puste `?tags=`
   znaczy „bez filtra" (wyczyszczony input), nieznana nazwa tagu nic nie wnosi
   i **nie jest błędem** — tag mógł zniknąć w innej karcie przeglądarki.
3. **Testy**: `tests/integration/test_tags.py` (8) i `test_watchlist.py` (5) —
   CRUD, 404 na cudzy zasób, 409 na duplikat nazwy, idempotencja `PUT`/`DELETE`,
   ta sama nazwa u dwóch użytkowników, nieistniejące `asset_id` → 404, filtr
   alokacji z osobnym kluczem cache. Test kształtu `WatchlistItemOut` pilnuje
   granicy zakresu: **brak `value_pln` i `quantity`** (CLAUDE.md #3.11).
4. **Dokumentacja**: `docs/model-danych.md` (cztery wiersze tabel + indeksy)
   i `docs/api-kontrakt.md` (sekcja „Tagi i listy obserwowanych", `?tags=`
   w tabeli struktury, segment `tags=` w opisie cache).

**43b — frontend (2026-08-26):**
- `lib/tags.ts` (+ `lib/tags.test.ts`, 7 testów) i `lib/watchlists.ts` — typy
  i wywołania 1:1 z kontraktem. Czyste funkcje filtra (`serializeTagFilter`,
  `parseTagFilter`, `toggleTag`) **sortują i odduplikowują** nazwy, żeby ten sam
  wybór dawał ten sam klucz TanStack Query i ten sam klucz cache po stronie API
  niezależnie od kolejności klikania.
- `components/tags/TagFilterBar.tsx` — chipy nad widokiem struktury. Kolor tagu
  **nigdy nie jest jedynym nośnikiem informacji** (CLAUDE.md §21): obok zawsze
  nazwa, stan wyboru niesie `aria-pressed` i obramowanie. Przy wyborze >1 tagu
  widok mówi wprost, że to suma, a nie przecięcie.
- `components/tags/PortfolioTagsPanel.tsx` — zarządzanie tagami przy pozycjach,
  z jawną informacją, że **tag opisuje spółkę, nie pozycję w tym portfelu**.
  Mapa `aktywo → tagi` składana z `GET /tags` + `GET /tags/{id}/assets`
  (`useQueries`); osobnego endpointu „tagi tego aktywa" świadomie nie dokładamy.
- **Pusty wynik filtra ma własny komunikat**, inny niż pusty portfel: „żadna
  pozycja nie ma wybranych tagów" plus przycisk czyszczenia — inaczej filtr
  wyglądałby na awarię.
- `components/watchlist/WatchlistsView.tsx` + trasa `/obserwowane` (z `AuthGuard`).
  Bez wyboru portfela: watchlista należy do użytkownika, nie do portfela.
- **Brak wpisu w nawigacji globalnej** — `NAV_ITEMS` ma pięć pozycji i to sufit
  dolnego paska na 375 px. Wejście z dashboardu portfela, tak jak przy dywidendach.

### Weryfikacja

- `ruff`/`mypy` (strict) zielone, backend **540 passed** — suita po raz pierwszy
  od 2026-08-25 w całości zielona.
- Frontend: `npm run lint`, `tsc --noEmit`, Vitest **84 passed**, `next build`
  z trasą `/obserwowane` w wykazie.

### Poprawki po code-review kroku 43 (2026-08-26)

Trzy znaleziska **blokujące** zamknięte przed pushem:

1. **`?tags=-` zatruwał klucz cache alokacji bez filtra.** Sentynel „brak filtra"
   (`tags=-`) był poprawną nazwą tagu, więc jedno wejście na `?by=class&tags=-`
   zapisywało **pustą** alokację pod kluczem zapytania **bez** filtra — przez cały
   6-godzinny TTL widok struktury pokazywał pusty portfel. Sentynelem jest teraz
   pusty string, nieosiągalny jako nazwa (`ck_tags_name_not_blank`), a nazwy idą
   do klucza przez skrót SHA-256, co przy okazji odcina zależność długości klucza
   Redisa od wejścia użytkownika. Test: `test_nazwa_tagu_nie_moze_udawac_braku_filtra`.
2. **Filtr tagów nie był wersjonowany.** Żaden segment klucza nie zmieniał się przy
   edycji `asset_tags` (`holdings_version` bumpuje tylko CRUD `holdings`,
   `eod_marker` to `MAX(prices.date)`), więc po odpięciu spółki od tagu backend
   przez 6 h oddawał wagi ze starym składem — mimo że frontend poprawnie
   unieważniał swój cache. Doszedł `tags/repository.tags_version`:
   `MAX(asset_tags.created_at)` **+** `COUNT(*)`, bo samo maksimum nie łapie
   usunięcia wiersza (ta sama pułapka co przy `valuations_marker`). Bez migracji —
   marker liczony z istniejącej tabeli, nie nowa kolumna. Test
   `test_zmiana_powiazan_tagu_nie_zostaje_w_cache` **zweryfikowany negatywnie**:
   po tymczasowym wyzerowaniu markera pada.
3. **Klucz API trafiał do Sentry w zmiennych lokalnych.** `sentry_sdk.init()` nie
   ustawiał `include_local_variables`, a domyślną wartością jest `True` — każdy
   `logger.exception` (w tym nowy, per symbol, w jobie dywidend) wysyłał ramki
   stosu z `api_key` i `params={"apikey": ...}`. Redakcja URL-a z kroku 47
   zamykała komunikat wyjątku, ta droga była szersza i obejmowała też Finnhuba
   oraz newsy z kroku 46. `include_local_variables=False` w `core/observability.py`.

Przy okazji: **limit `?tags=`** — najwyżej 20 nazw (powyżej `422`, bo ciche obcięcie
oddawałoby wynik innego pytania niż zadane), nazwy dłuższe niż 60 znaków pomijane.

### Zostaje po kroku 43 (nieblokujące)

- **Wybór tagów nie jest w adresie URL** — odświeżenie strony gubi filtr.
  `parseTagFilter` jest już napisane pod `useSearchParams`, brakuje tylko spięcia.
- **`PATCH /tags/{id}` bez UI** — nazwy i koloru nie da się dziś zmienić z ekranu
  (API to umie); tag trzeba usunąć i założyć od nowa.
- **Notatka przy pozycji watchlisty tylko do odczytu** — `PUT` przyjmuje `note`,
  ale widok dodaje pozycje z `note: null`.
- **Karta koncentracji obok przefiltrowanej alokacji** liczy HHI całego portfela
  i nie mówi tego na ekranie (CLAUDE.md §21) — do dopisania jednym zdaniem.
- **Licznik przy chipie tagu jest globalny**, a widok struktury dotyczy jednego
  portfela: „dywidendowe (5)" może dać pusty wynik w tym portfelu.
- **`holdingsQuery` w widoku struktury bez `ErrorState`** — przy błędzie panel
  tagów znika bez śladu, nie do odróżnienia od portfela bez pozycji.
- **Liczniki joba dywidend zawyżają przy błędzie commita** — `fetched`/`stored`
  inkrementowane przed `commit()`, `rollback()` ich nie cofa.
- **Harness izolacji: brak strony pozytywnej dla tagów/watchlist** i asercja
  dopuszczająca `422` (trasa walidująca przed sprawdzeniem własności przeszłaby
  test, nie sprawdziwszy niczego).
- **Tag z przecinkiem w nazwie** jest nierozpoznawalny przez `?tags=`.
- **Brak filtra tagów w innych widokach** (wyniki, ryzyko, kalendarz dywidend) —
  dziś tylko alokacja przyjmuje `?tags=`.

## Krok 41b — metryki ryzyka (ZROBIONY 2026-08-25)

Zmienność, Sharpe, max drawdown z wykresem underwater, beta i heatmapa zwrotów
miesięcznych. Konsument stopy referencyjnej z kroku 41a.

**Co powstało:**
- `backend/app/modules/analytics/risk.py` — czysta matematyka bez I/O (jak `returns.py`
  i `benchmark.py`): `volatility`, `sharpe`, `beta`, `max_drawdown`, `underwater`,
  `monthly_returns`, `risk_free_daily`. Reużywa `benchmark.as_of_values` do wyrównania
  stopy do dat (to ta sama reguła `max(effective_from) <= D`).
- `service.risk` + `GET /portfolios/{id}/risk?range=&benchmark=` (`RiskOut`), cache Redis
  z **własnym segmentem świeżości dla stopy referencyjnej** — przychodzi z tygodniowego
  joba, więc żaden z pozostałych markerów by nie drgnął przy decyzji RPP.
- Frontend: `lib/risk.ts`, `components/dashboard/RiskPanel.tsx`,
  `components/charts/UnderwaterChart.tsx`, `components/charts/MonthlyReturnsHeatmap.tsx`,
  podstrona `app/portfolios/[id]/ryzyko`, link z dashboardu, klucz `qk.risk`.
- `docs/api-kontrakt.md` — sekcja `/risk` z pełnym przykładem i uzasadnieniami.

**Decyzje projektowe:**
- **Wszystko liczone z ogniw i indeksu łańcuchowego**, nigdy z `value_pln` (ADR-101):
  wpłata to nie zmienność i nie wyjście z obsunięcia.
- **Jedno ogniwo = jedna obserwacja**, annualizacja przez √252. Ważenie ogniw długością
  wymagałoby kalendarza sesji per rynek, którego portfel wielorynkowy nie ma jednego.
- **Próg `MIN_OBSERVATIONS = 20`** dla zmienności, Sharpe'a i bety. Drawdown progu **nie
  ma** — jedno obsunięcie jest faktem, a nie oszacowaniem rozkładu.
- **Osobny `*_unavailable_reason` na metrykę.** Przy tej samej serii zmienność bywa
  policzalna, a Sharpe nie (brak stopy NBP). Jeden wspólny komunikat kłamałby o jednym.
- **Sharpe na stopie zmiennej w czasie**; dni bez stopy wypadają **w parze** ze swoim
  zwrotem, żeby nie przyjąć po cichu rf = 0.
- **Beta parowana po datach** (`previous_date → date`), nie zestawiana obok siebie —
  ogniwa portfela bywają pomijane, więc naiwne zestawienie przesunęłoby serie.
- **Heatmapa składa ogniwa**, nie dzieli indeksu z krańców miesiąca (w miesiącu ze
  zmianą składu indeks stoi na zerwanym ogniwie).
- **Podstrona `/ryzyko`, nie sekcja na dashboardzie** — dashboard trzyma zasadę 5–7 KPI
  (CLAUDE.md §21), a to pięć wskaźników i dwa wykresy.
- **Dostępność:** heatmapa to tabela HTML z liczbami w komórkach i nagłówkami wierszy/
  kolumn (nie kanwas), paleta niebieski/pomarańczowy zamiast zielony/czerwony,
  miesiąc bez danych jest pusty i opisany, a nie pokazany jako zero. Miesiące policzone
  z mniej niż 5 dni dostają gwiazdkę „dane niepełne" (CLAUDE.md #3.15).

**Weryfikacja:** 47 nowych testów (30 jednostkowych `test_risk.py` — wartości oczekiwane
z **niezależnej implementacji** `statistics` ze stdlib, nie przepisane z naszego kodu;
16 integracyjnych `tests/integration/test_risk.py`, w tym beta = 1 i beta = 2 jako
przypadki referencyjne end-to-end, 404 na cudzy portfel i test „brak stopy zabiera
Sharpe'a, nie zmienność"; 9 frontendowych `lib/risk.test.ts`). Cała suita backendu
**506 passed** (było 459), frontend **77 passed** (było 68). `ruff format --check`,
`ruff check`, `mypy app worker`, `tsc --noEmit`, `eslint`, `next build` — zielone.
Trasa `/portfolios/[id]/ryzyko` buduje się jako dynamiczna.

**Weryfikacja na żywych danych** (dev, po `seed-history` od 2025-01-02, 429 dni):
`range=max` → 428 obserwacji, zmienność 0,3063, drawdown −0,3964 (2025-10-06 →
2026-02-05, nieodrobiony), beta wobec `^GSPC` 0,884, 20 miesięcy na heatmapie.
`range=1Y` z benchmarkiem WIG20 → Sharpe −0,895185 przy etykiecie „Stopa referencyjna
NBP (historyczna)", beta 0,284 z `approximate=true`.

**Uwaga operacyjna:** fixture `clean_rates` w `tests/integration/test_risk.py` czyści
całą tabelę `nbp_reference_rates` (potrzebny jest przypadek pustej tabeli), więc
**po przebiegu suity na bazie dev Sharpe znika**, dopóki nie uruchomi się ponownie
`ingest_nbp_rates`. Ta sama klasa problemu co przy dywidendach — baza testowa i dev
to jedna instancja.

**Nie zrobione (świadomie):** świeżość serii stóp nadal nie jest pokazana
w `/meta/freshness`. Metryki nie są wystawione na głównym dashboardzie ani w API
zbiorczym — wejście jest przez podstronę `/ryzyko`.

## Krok 46 — newsy (ZROBIONY 2026-08-11: backend, Finnhub, Alpha Vantage, frontend)

**Co powstało:** `news`/`news_assets` + migracja `20260810_news_i_news_assets.py` (round-trip
`upgrade → downgrade → upgrade` przetestowany, oba indeksy realnie `DESC` — sprawdzone
w `pg_indexes`) · `modules/news/` (`models`, `matching`, `repository`, `service`, `schemas`,
`routes`) · `modules/news/providers/` (`base` z `NewsProvider`/`GuardedNews`, `rss`) ·
`worker/jobs/ingest_news.py` + rejestracja w `scheduler.py` (interwał 30 min) ·
`tests/unit/test_news_matching.py` (22 testy) · `feedparser==6.0.11` · wpis w `api-kontrakt.md`
i `model-danych.md`.

**Osobny protokół `NewsProvider`, nie rozszerzenie `DataProvider`.** Tamten opisuje trzy
operacje per symbol (OHLCV/FX/metadane); feed RSS nie przyjmuje symbolu i oddaje strumień
wszystkiego. Dopisanie tam `get_news` zmusiłoby NBP, Stooq i Binance do implementowania metody,
której nigdy nie wywołają. `GuardedNews` reużywa **te same** klasy `RateLimiter`
i `CircuitBreaker` — powielona jest wyłącznie pętla delegująca (§4.3: bez refaktoru cudzego
modułu przy okazji).

**`GET /portfolios/{id}/news` — nie ma trasy „wszystkie newsy".** Powód produktowy (§1: ekran
odpowiada na „co z moimi pozycjami", nie „co w gospodarce"), efekt uboczny bezpieczeństwowy:
każda trasa newsowa przechodzi przez `get_owned_portfolio`. Parametryzowany test izolacji
**sam wykrył nową trasę** i przeszedł (`['GET']:/api/portfolios/{portfolio_id}/news`) — dokładnie
to, co obiecuje §3.10.

### Trzy błędy, które wyszły dopiero na żywych feedach

Żaden nie wyszedłby z testów jednostkowych ani z przeglądu kodu — wszystkie trzy to dopasowania,
które wyglądały na działające, dopóki nie zobaczyło się, co realnie tagują.

1. **`Złoto` → token `oto`.** `ł` nie jest literą bazową z diakrytykiem, więc `NFKD` jej nie
   rozkłada, a `_tokenize` traktuje nierozpoznany znak jak separator: „złoto" rozpadało się na
   „z" + „oto". `oto` jest pospolitym polskim słowem, więc XAU tagowało się do „**Oto** gdzie
   szukać okazji". Naprawione jawną podmianą (`_NON_DECOMPOSABLE`) **przed** NFKD.
2. **`NASDAQ 100` → token `100`.** Pasował do każdej setki w tekście — indeksy lądowały przy
   wiadomości o oprocentowaniu konta i o tabletce na odchudzanie. Tokeny czysto liczbowe odrzucone.
3. **`CD Projekt` → token `projekt`.** Nazwa spółki będąca pospolitym rzeczownikiem; CDR tagowało
   się do „jest **projekt** ustawy o refundacji pomp insulinowych". Naprawione wymogiem **wielkiej
   litery** dla tokenów nazwy — w polszczyźnie nazwa własna jest kapitalizowana, rzeczownik
   pospolity w środku zdania nie. Pozostaje znana, świadomie przyjęta dziura: pierwszy wyraz
   nagłówka jest kapitalizowany zawsze.

Każdy z trzech ma test regresyjny. Po naprawach: 74 pobrane pozycje → 3 zapisane, 5 powiązań,
**zero fałszywych trafień** (przed naprawami 8 powiązań, z czego 5 błędnych). Kierunek pomyłki
jest świadomie zaniżający: news bez tagu nie pojawi się w feedzie, zamiast pojawić się przy złej
spółce.

### Znaleziska po stronie źródeł

- **money.pl** oddaje `301` z `/rss/all.xml` na `/rss/rss.xml`, a `httpx` **domyślnie nie podąża
  za przekierowaniami** — poprawny feed wyglądał jak padnięty. Stąd `build_rss_client()`
  z `follow_redirects=True`.
- **StockWatch** odrzuca żądanie bez `User-Agent` (403), a jego `/feed/` w ogóle nie jest feedem
  — oddaje stronę HTML (wykryte przez kontrolę `bozo`, ta sama klasa co HTML ze Stooqa
  w etapie 8). Działający adres to `https://www.stockwatch.pl/wiadomosci/feed/`.
- Przedstawiamy się własnym `User-Agent` z adresem aplikacji, **nie** podszywamy się pod
  przeglądarkę — wydawca ma móc nas zablokować celowo, jeśli sobie tego życzy.

### Domknięcie kroku 46 — front, Finnhub i sentyment (2026-08-11)

**Finnhub daje pewność powiązania, nie sentyment.** Sprawdzone realnym kluczem:
`/news-sentiment` → `403 {"error":"You don't have access to this resource."}` na darmowym
planie, `/company-news` działa. Wartością Finnhuba jest więc to, że **źródło samo wskazuje
spółkę** — stąd kolumna `news_assets.match_confidence` (`source` vs `heuristic`) i migracja
`20260810_news_assets_match_confidence.py`. Osobny `FinnhubNewsProvider`, nie metoda
w `marketdata/providers/finnhub.py`: tamten implementuje `DataProvider` i ma zaszyty URL świec,
więc dopisanie tam newsów byłoby refaktorem cudzego obszaru przy okazji (§4.3).

**Sentyment: Alpha Vantage `NEWS_SENTIMENT`** (działa na darmowym planie — sprawdzone).
Nowy `AlphaVantageNewsProvider` + `BatchNewsProvider` (jedno zapytanie na wiele tickerów)
+ **osobny job** `ingest_news_sentiment` co 120 min. Osobny, bo `ingest_news` chodzi co 30 min
= 48 przebiegów, a darmowy plan AV to **25 zapytań na dobę** — wspólny harmonogram wyczerpałby
budżet przed południem i dostawca zacząłby zwracać komunikat o limicie, czyli otwierałby
bezpiecznik bez powodu. `?with_sentiment_only=true` przestał być filtrem, który zawsze zwraca
pustą listę.

**Próg trafności 0,9 dla Alpha Vantage — znalezione dopiero na żywych danych.**
`ticker_sentiment` wymienia każdą wspomnianą spółkę i przy zapytaniu o konkretne tickery
**zawyża im trafność**: artykuł „Apple Downgraded as Soaring Memory Costs Test iPhone Pricing
Power" dostał MSFT z wynikiem 0,61. Pierwszy przebieg dał **100 powiązań z 50 artykułów**
(każdy artykuł do obu spółek), choć tylko 6 z nich w ogóle wspominało Apple lub Microsoft
w tytule. Zmierzone progi: 0,5 → 100 powiązań, 0,7 → 24, **0,9 → dokładnie te 6**. To nie było
strojenie pod estetykę feedu: te powiązania zapisujemy jako `source`, czyli UI pokaże je jako
fakt, a „wspomniano nazwę spółki" nie jest faktem „ten news dotyczy Twojej pozycji" (#3.15).

**`overall_sentiment_score`, nie `ticker_sentiment_score`.** `news.sentiment` jest kolumną
newsu, nie pary news–aktywo, więc ocena per spółka zależałaby od tego, o który symbol
zapytaliśmy pierwsi (`ON CONFLICT DO NOTHING`) — cichy niedeterminizm. Ocena per spółka
wymaga kolumny w `news_assets` i jest świadomie poza zakresem tego kroku.

**Finnhub: okno 2 dni zamiast 7 w jobie cyklicznym.** Pierwszy przebieg dał 248 pozycji na
symbol; przy jobie co 30 min siedmiodniowe okno to pobieranie w kółko tego samego.

**Frontend** (`app/newsy/` + `app/portfolios/[id]/newsy/`, `components/news/NewsFeedPanel.tsx`,
`lib/news.ts`): feed z filtrem sentymentu, znacznikami aktywów i notą o pozycjach bez newsów.
`match_confidence` dojeżdża do UI **per aktywo** (`assets[]` w odpowiedzi, zawężone do aktywów
pytającego portfela — wiersz `news` jest współdzielony, więc nieprzefiltrowana lista zdradzałaby
cudze pozycje). Powiązanie zgadnięte ma przerywaną obwódkę i znak „?", nie sam kolor; brak oceny
sentymentu napisany wprost („brak oceny wydźwięku"), bo puste miejsce wygląda jak ładowanie.
Piąta pozycja nawigacji zmierzona zrzutem Playwrighta na 375 px — najdłuższa etykieta
(„Struktura") dostaje 55 px i **nie jest przycięta**; szósta wymagałaby przebudowy paska.

**Testy:** `tests/integration/test_news.py` (8, w tym dwóch użytkowników widzących **ten sam
wiersz `news` z różnymi listami `assets`**) · `tests/unit/test_alphavantage_news_provider.py`
(15) · `frontend/lib/news.test.ts` (14). Backend **332 passed**, ruff + mypy czyste,
frontend lint + tsc + vitest + build zielone.

### Code-review kroku 46 (2026-08-11) — znaleziska naprawione

Dwa **blokujące**, oba realne:

1. **`with_sentiment_only` filtrował PO `LIMIT`.** Zapytanie brało 50 najnowszych newsów, dopiero
   potem odsiewało te bez oceny — więc portfel z przewagą GPW (same polskie feedy wśród
   najnowszych) dostawał pustkę, choć ocenione newsy o spółkach zagranicznych leżały dzień
   głębiej. UI mówił wtedy „żaden news o Twoich pozycjach nie ma oceny wydźwięku" — zdanie
   **fałszywe**, którego użytkownik nie miał jak rozpoznać (#3.15). Zawężenie przeniesione do
   zapytania; `limit` znowu znaczy „tyle pozycji". Test regresyjny: 5 świeżych bez oceny,
   2 starsze z oceną, `limit=3` — stary kod zwracał 0 pozycji.
2. **Niezmiennik „`source` nigdy nie schodzi do `heuristic`" nie miał testu.** Usunięcie klauzuli
   `where` z `link_news_to_assets` przechodziło całą suitę, a w produkcji przy najbliższym
   przebiegu RSS przeetykietowałoby każde powiązanie od dostawcy jako zgadywankę. Dwa testy
   integracyjne na oba kierunki.

Do poprawy, naprawione:

- **`_store` gubił powiązanie przy konflikcie na `content_hash`** — czyli dokładnie w scenariuszu
  „ta sama depesza pod innym adresem", dla którego ta ścieżka powstała. Dopisane
  `get_news_id_by_content_hash`.
- **Tickery z `^` nie dopasowywały się NIGDY.** `\b` przed `^` nie jest granicą słowa, więc nawet
  dosłowne „^NDX" wracało z `findall` jako `NDX` i porównanie z `^NDX` dawało `False`. Indeksy
  zagraniczne rozpoznawały się wyłącznie po członie nazwy. Stary test tego nie łapał, bo
  „FTSE 100" trafiał tokenem nazwy, nie tickerem.
- **SQL w warstwie serwisu** przeniesiony do repozytorium (§8), lokalny import usunięty.
- **Brak nowych zmiennych w `.env.example` i `.env.prod.example`** (#3.9) — dopisane
  `NEWS_RSS_FEEDS`, `NEWS_MAX_AGE_DAYS`, `RATE_LIMIT_RSS`, `RATE_LIMIT_ALPHAVANTAGE`.
- Kolizja `provider_symbol` w Alpha Vantage (dwa aktywa, ten sam ticker) cicho gubiła jedno
  aktywo w sposób zależny od kolejności wierszy — teraz `logger.warning`.
- `counters.linked` → `upserted`: `RETURNING` po `DO UPDATE` liczy też podniesienia pewności,
  więc nie była to liczba NOWYCH powiązań.
- `isinstance(ts, (int, float))` przepuszczał `bool` (Finnhub); duplikacja `title` + `sr-only`
  na znaczniku aktywa; komentarz uzasadniający `Number()` w `sentimentTone`.

Świadomie **nie** naprawione (uzasadnienie, nie przeoczenie): jedna transakcja na cały przebieg
joba oraz `ix_news_published_at_desc` bez dzisiejszego konsumenta — jedno i drugie to zmiany
projektowe wykraczające poza krok 46.

### Znane ograniczenie dopasowania — zmierzone, wymaga decyzji

Po naprawach żywy przebieg dał **5 powiązań heurystycznych, z czego 2 błędne** (obie do `CDR`):
depesza o fotoradarach i o dofinansowaniu Ryvu Therapeutics. Przyczyna to udokumentowana wcześniej
dziura „pierwszy wyraz zdania jest kapitalizowany zawsze" — obie depesze mają w skrócie zdanie
zaczynające się od „Projekt".

Sedno problemu jest węższe: `CD Projekt SA` po odfiltrowaniu tokenów krótszych niż 3 znaki (`CD`)
i stopwordów (`SA`) zostaje z **jednym** tokenem `projekt`, będącym pospolitym polskim
rzeczownikiem. Dwuwyrazowa nazwa własna zamienia się w słowo generyczne.

Propozycja do rozstrzygnięcia (nie wdrożona — zmienia semantykę dopasowania, więc poza kroku 46):
zachować krótkie tokeny dla nazw wielowyrazowych i wymagać **kompletu** tokenów. `CD Projekt`
wymagałoby wtedy `CD` **i** `Projekt`, co odcina oba fałszywe trafienia bez ruszania nazw
jednowyrazowych (`Orlen`). Do czasu decyzji te powiązania są w UI jawnie oznaczone jako
przybliżenie (przerywana obwódka + „?"), więc nie są przedstawiane jako fakt.

### Zostaje po kroku 46

- **Tagowanie po watchlistach** — czeka na krok 43 (decyzja 1 planu etapu 9).
- **Sentyment per spółka** (`news_assets.sentiment`) — dziś ocena dotyczy całego artykułu.
- **Pokrycie sentymentu tylko dla US** — mapowań `alphavantage` jest dwa (AAPL, MSFT);
  polskie spółki nie mają i nie będą miały darmowego źródła oceny.

### Krok zerowy — pozostałe blokujące z code-review naprawione (2026-08-10)

Cztery blokujące znaleziska z recenzji kroku zerowego domknięte. Kolumna `prices.source`
(sekcja wyżej) była pierwszym; tutaj reszta.

**#1 dokończone — przypięcie dostawcy i wykrywanie wymieszanej konwencji.** Sama kolumna
dawała wykrywalność, nie zapobieganie. Doszło `backfill-prices --provider yfinance`
(`make backfill provider=yfinance`), które przypina wszystkie okna do jednego dostawcy —
bez tego łańcuch rozstrzyga się per okno i potrafi zejść w połowie pięcioletniego backfillu
na innego dostawcę. Doszło też `price_series_diagnostics` w repozytorium: liczy wiersze
skorygowane (`close_adj <> close`) i nieskorygowane osobno, zbiera źródła, a `mixed_convention`
zapala się, gdy jedno i drugie jest niezerowe. Backfill kończy się wtedy **kodem 1** i wypisuje,
które serie zaciągnąć od nowa. Wiersze z `close IS NULL` (NBP, złoto) nie wpadają do żadnego
licznika — nie da się o nich powiedzieć, czy są skorygowane, a wrzucenie ich do
„nieskorygowanych" fałszowałoby obraz aktywów bez OHLC.

**#2 — licznik mierzy deltę, nie stan bazy.** `backfill_prices` zwraca teraz listę
`BackfillTarget` zamiast `dict[str, int]`: `rows_before`, `rows_after`, `windows_failed`,
`windows_total`, `unavailable`, `diagnostics`. Raportowaną liczbą jest `rows_added`.
Poprzednia wersja liczyła stan bazy, więc aktywo z 12 wierszami sprzed przebiegu pokazywało
„12 notowań" także wtedy, gdy każde okno padło. **Cele z zerem wierszy nie znikają już
z raportu** (`if rows:` usunięte) — przy dwudziestu aktywach raport z siedemnastoma pozycjami
nie mówi, których trzech brakuje. `_run_backfill` zwraca 1, gdy **żaden** cel nie ma wierszy
w bazie (nie „gdy nic nie przybyło" — powtórzony backfill na komplecie danych daje zerową
deltę i jest sukcesem) oraz gdy wykryto wymieszaną konwencję.

**#3 — `seed-history` broni dolnej granicy zakresu.** Nowe `held_asset_price_coverage`
(`portfolio/repository.py`) liczy **maksimum z najwcześniejszych dat notowań per trzymane
aktywo** — dopiero od tego dnia każda pozycja ma cenę. Start przed tym dniem albo aktywo bez
ani jednej ceny → odmowa z kodem 2 i konkretną datą do podstawienia. Powód: silnik wyceny
pomija pozycję bez ceny zamiast liczyć ją jako zero, więc wcześniejsze dni dają wyceny
cząstkowe, nieodróżnialne potem od pełnych — seria zaczynałaby się blisko zera i skakała
w miarę „pojawiania się" pozycji, dając krokowi 40 absurdalny zwrot, a krokowi 41 drawdown
100%. `--allow-incomplete` dopuszcza to świadomie i dopisuje ostrzeżenie do wyniku.

**#4 — testy.** 39 nowych: `tests/unit/test_backfill_chunks.py` (7 — granice okien NBP,
komplet pokrycia, zakres odwrócony), `tests/integration/test_backfill_prices.py` (8 — delta
licznika na aktywie z historią, cele bez danych w raporcie, porażka jednego celu nie zabija
reszty, `unavailable` vs pustka, przypięcie dostawcy, wykrycie wymieszanej konwencji),
`test_cli_seed_history.py` (8 — guardy `ENV`/zakresu/pokrycia sprawdzane **na wywołaniu
`snapshot_portfolios`**, nie na kodzie wyjścia), `test_portfolio_repository_coverage.py` (4 —
`first_full_date` jako maksimum z minimów), `test_seed_reference.py` (2 — idempotencja
i regresja `GPW → WIG20`), plus 5 w `test_marketdata_repository.py` (granice `count_*_in_range`,
diagnostyka konwencji).

**Przy okazji, bo w tych samych funkcjach:** `date.today()` → `portfolio_service.today()`
w CLI (konwencja repo — `date.today()` zależy od strefy serwera), guard `start > end`
w `seed-history`, `to=` i `provider=` faktycznie przekazywane przez `Makefile` (`to=` było
cicho ignorowane), przerwanie pętli okien po `ProviderUnavailableError` (presja na
`CircuitBreaker` spada z 5N do N prób).

**NIE naprawione** (świadomie, poza zakresem „blokujących"): fail-open blokady `ENV`, gdy
zmienna nie jest ustawiona (#5); nadpisywanie istniejących snapshotów przez `seed-history`
razem z flagami `composition_change` (#6); drobiazgi #11-#17 z recenzji.

**Weryfikacja (powtórzona 2026-08-11):** `ruff`, `ruff format` i `mypy --strict` czyste **dla
plików etapu 8** — błędy, które zgłaszają, siedzą wyłącznie w module `news` pisanym równolegle
w innej sesji (`app/modules/news/*`, `worker/jobs/ingest_news.py`), więc `make check` jako
całość jest czerwony nie z powodu tych zmian. Backend: **312 testów zielonych** w obu
kolejnościach (`-p no:randomly` i z domyślną randomizacją), `test_analytics.py` uruchomiony
sam też przechodzi. Wcześniejszy przebieg z 8 błędami w `test_analytics.py` **nie jest
odtwarzalny** — padał na `db.refresh(user)` przy rejestracji, w kodzie nietkniętym tymi
zmianami, w czasie gdy druga sesja pisała do tej samej bazy dev i puszczała migracje.
Nie mam dowodu na przyczynę i nie przypisuję jej tym zmianom. Uwaga:
`test_rate_limit.py::test_default_limit_is_per_path` padł **raz** na jednym z przebiegów
i przeszedł zarówno osobno, jak i w dwóch kolejnych pełnych suitach — to **istniejąca
wcześniej niestabilność**, nie skutek tych zmian. Przyczyna jest w `core/rate_limit.py:124`: okno limitera to
`int(time.time()) // 60`, więc pętla żądań rozłożona na granicy minuty zeruje licznik i
oczekiwane 429 nie przychodzi. Ryzyko rośnie wraz z czasem trwania suity, a ta urosła o 39
testów. Właściwą naprawą jest zamrożenie zegara w tym teście (jest już `tests/unit/_fake_clock.py`),
nie retry.

### Krok zerowy — DOMKNIĘTY DANYMI (2026-08-12)

Narzędzia z sekcji wyżej puszczone na żywej bazie dev. **Etap 8 ma wreszcie szereg czasowy.**

**Stan końcowy:** `portfolio_valuations` **1305 wierszy** (2021-08-12 .. 2026-08-12, jeden
portfel demo, 522 dni weekendowych pominięte), `AAPL`/`MSFT` po 1254 notowania, `CDR`/`PKN`
po 1249, `bitcoin` 1827 (24/7), kursy NBP `USD`/`EUR`/`CHF`/`GBP`/`HKD`/`JPY` po 1260.
Benchmarki z poprzedniej sesji bez zmian (`^GSPC` 1254, `ETFBW20TR` 1250). Próg 30 obserwacji
z kroku 41 przekroczony ~40-krotnie.

**Backfill musiał pójść w dwóch przebiegach, nie jednym.** `--provider yfinance` filtruje
łańcuch per rynek, więc rynek `FX` (łańcuch: sam NBP) zostałby pominięty z ostrzeżeniem
`provider_not_in_chain` — a bez kursów USD/PLN wycena `AAPL`/`MSFT`/`bitcoin` nie ma z czego
powstać. Kolejność: `--symbol … --provider yfinance` dla aktywów, potem `--market FX` bez
przypięcia. Warte dopisania do `Makefile` przy okazji kroku 40.

**`_clean_auth_tables` z `tests/conftest.py` kasuje dane dev.** `TRUNCATE users CASCADE`
przed każdym testem zabiera portfele, pozycje i `portfolio_valuations` — baza dev i testowa
to nadal ta sama baza (dług z etapu 2, udokumentowany w docstringu `conftest.py`). Praktyczny
wniosek na czas etapu 8: **`make seed` + `seed-history` po każdym pełnym przebiegu testów**,
inaczej dashboard i metryki liczą na pustce. Ceny i kursy przeżywają (nie są zasobem
użytkownika), więc powtórka jest szybka i bez ruchu sieciowego.

**Przy okazji: sprzątnięte wycieki fixture'ów w bazie dev** — 6 aktywów `COV*`
(`test_portfolio_repository_coverage.py`) z 6 cenami i 1 aktywo `ANL*` w walucie `XTS`
(`test_analytics.py`). To ostatnie przeciekało do produkcyjnej ścieżki: `list_fx_currencies`
liczy waluty z `assets.currency`, więc `XTS` pojawiło się jako **cel backfillu kursów NBP**
(„brak danych"). Wyciek fixture'a nie kończy się na śmieciach w słowniku.

**Weryfikacja semantyki na żywych danych:** powtórzony backfill dał `+0 nowych, 1254 w bazie`
i **kod 0** — dokładnie to, o co chodziło w poprawce #2 (zerowa delta na komplecie danych jest
sukcesem). Guard pokrycia z #3 nie odmówił, bo po backfillu wszystkie pięć pozycji zaczyna się
2021-08-12. Skoki d/d w serii wycen (`-13,7%` 2022-06-13, `-10,1%` 2024-08-05, `+11,1%`
2024-11-11) odpowiadają realnym epizodom rynkowym przy portfelu z bitcoinem, a nie wycenom
cząstkowym; `get_latest_prices(on_date=…)` filtruje `date <= on_date`, więc święta GPW niosą
ostatni kurs, zamiast wycinać pozycję z wyceny. `composition_change` wyszło `false` **we
wszystkich 1305 dniach** — dokładnie jak przewidywał plan, więc zrywania ogniwa w kroku 40
ta historia nie przećwiczy i muszą to zrobić testy jednostkowe.

### Blokada `mixed_convention` była fałszywym alarmem — naprawione 2026-08-12

Pierwszy realny backfill zapalił BLOKADĘ na **wszystkich czterech** akcjach, mimo że każda
seria pochodziła w 100% z yfinance: `AAPL 1252/2`, `MSFT 1198/56`, `PKN 1210/39`,
`CDR 969/280` (skorygowanych/nieskorygowanych).

**Przyczyna:** kryterium `adjusted_rows > 0 and unadjusted_rows > 0` nie mierzy konwencji.
Współczynnik korekty jest z definicji równy 1 dla ogona serii — po ostatniej dywidendzie albo
splicie nie ma czego korygować — więc **każda** czysta seria yfinance kończy się wierszami
`close_adj == close`. Liczba „nieskorygowanych" to po prostu liczba sesji od ostatniej
dywidendy (AAPL 2 dni, CDR 280). Blokada zapalałaby się zawsze i po tygodniu zostałaby
wyłączona jako hałas — czyli mechanizm z blokującego #1 przestałby chronić przed czymkolwiek.

**Naprawa:** kryterium blokady to `mixed_sources` — liczba różnych wartości `prices.source`
w serii. Po to ta kolumna powstała (migracja `926b382d1715`). `mixed_convention` usunięte,
`adjusted_rows`/`unadjusted_rows` zostają jako informacja diagnostyczna („czy ta seria
w ogóle jest korygowana"). `NULL` liczy się jako osobna wartość: wiersze sprzed migracji mają
nieznane pochodzenie i seria pół-NULL/pół-yfinance jest genuinely podejrzana. Dwóch dostawców
o tej samej konwencji zapali się niepotrzebnie — fałszywy alarm w bezpieczną stronę, a naprawa
jest ta sama i tania.

**Dlaczego nie złapały tego testy:** oba istniejące używały serii dwuwierszowej, w której
wiersz nieskorygowany był *jednocześnie* od innego dostawcy — więc obie flagi zapalały się
razem i nie dało się odróżnić, która działa. Doszły dwa testy rozdzielające te przypadki:
`test_single_provider_series_is_not_mixed_despite_both_conventions` (regresja wprost na tym
układzie) i `test_rows_without_source_count_as_own_provenance`.

## Krok 40 — zwroty dzienne ze snapshotów (ZROBIONY 2026-08-12)

`GET /portfolios/{id}/performance?range=1M|3M|1Y|YTD|max`. Warstwa czysta:
`app/modules/analytics/returns.py` (`daily_returns`, `chain_link`, `chain_index`,
`period_return` — zero I/O, zero Pydantic, wszystko na `Decimal`), orkiestracja w
`analytics/service.performance`, schematy i trasa dołożone do istniejących plików modułu.

**Zwrot jest łańcuchowy, nie ilorazem krańców.** Snapshoty nie znają przepływów (ADR-101),
więc `V_koniec / V_start - 1` policzyłoby dopłatę jako zysk. Ogniwo `t-1 → t` w dniu
`composition_change=true` wypada, ale `V_t` zostaje bazą ogniwa następnego — skasowanie
obu dni (częsty odruch) wycięłoby prawdziwy zwrot dnia po dopłacie.

**Trzy rozstrzygnięcia, których plan zostawiał otwartymi:**

1. **Przerwa w serii łączy** (decyzja 6 planu potwierdzona w kodzie), a odpowiedź niesie
   `links` — liczbę ogniw, które faktycznie weszły do iloczynu. Bez tego „zwrot za 1Y"
   policzony z 40 ogniw wygląda identycznie jak ten z 250.
2. **`ret=null` ≠ `ret="0"`.** `null` znaczy „nie znamy" (pierwszy punkt, zerwane ogniwo),
   zero znaczy „portfel nic nie zarobił". Tak samo `period_return=null` dla portfela bez
   historii. CLAUDE.md #3.15 — dane niepełne muszą być oznaczone, nie dopchnięte zerem.
3. **Pominięcia rozdzielone po powodzie:** `skipped_composition_change` (zadziałał ADR-101,
   stan normalny) i `skipped_zero_base` (zwrot z zerowej bazy — sygnał, że dane wyglądają
   źle). Jeden wspólny licznik zlewałby rzecz zamierzoną z podejrzaną.

**`index` (baza 100) jest w odpowiedzi od razu, nie dopiero w kroku 42.** Krok 41 wymaga
drawdownu liczonego na indeksie łańcuchowym, a nie na `value_pln` (inaczej wpłata wygląda
jak wyjście z obsunięcia), a krok 42 — obu serii znormalizowanych do 100. Liczenie tego
teraz kosztowało jedną funkcję i pilnuje, żeby wykres i zwrot pod nim wychodziły z tych
samych ogniw (jest na to test).

**Cache ma INNY marker niż reszta modułu.** `valuations_marker` = `MAX(date)` **i**
`COUNT(*)` z `portfolio_valuations` (`portfolio/repository.py`), nie `_eod_marker`. Powód
jest wprost z kroku zerowego: snapshoty przybywają też **wstecz** — `seed-history` dopisuje
lata historii, nie ruszając maksimum. Klucz na samym `MAX` dałby po takim przebiegu
trafienie w cache ze zwrotem policzonym z krótszej serii, czyli błędną liczbę podaną z
pełnym przekonaniem aż do wygaśnięcia TTL. Jest na to test regresyjny.

**Zakres `range` reużywa `ValuationRangeParam` z `portfolio/routes.py`** zamiast drugiego
enuma o tych samych wartościach — obie trasy schodzą do tego samego `_range_start`, więc
rozjazd list dałby „422 na `1M`, które gdzie indziej działa".

**Testy:** 18 jednostkowych (`tests/unit/test_returns.py`, na znanych liczbach, bez bazy —
w tym przykład ze skilla: 1000 → dopisana pozycja 500 → 1500, zwrot za ten dzień NIE
ISTNIEJE) + 11 integracyjnych (`tests/integration/test_performance.py` — autoryzacja,
`range`, serializacja do stringów, awaria Redisa, unieważnienie cache przy historii
dopisanej wstecz). Harness izolacji z CLAUDE.md #10 złapał nową trasę automatycznie
(`test_user_b_cannot_touch_user_a_resources[['GET']:/api/portfolios/{portfolio_id}/performance]`).

**Weryfikacja:** `ruff`, `ruff format --check`, `mypy` czyste na całym backendzie,
**375 testów zielonych**. Próba na realnych danych dev (1305 snapshotów, portfel demo):

```
1M   +4,00%    22 ogniwa   2026-07-13..2026-08-12   indeks 104,0032
1Y  -29,03%   261 ogniw    2025-08-12..2026-08-12   indeks  70,9688
max +57,00%  1304 ogniwa   2021-08-12..2026-08-12   indeks 157,0008
```

Kontrola niezależna: historia nie ma ani jednej zmiany składu, więc łańcuch musi się zgadzać
z ilorazem krańców — 41500,94 / 26433,59 = 1,5700. Zgadza się.

**Zostaje po kroku 40 (nieblokujące):**

- Frontendu jeszcze nie ma — wykres wyników jest częścią kroku 42 (benchmark), zgodnie
  z planem etapu. Endpoint jest gotowy do podpięcia.
- `period_return` kwantyzowany do 4 miejsc (`_PCT_QUANT`), zwrot dzienny do 6
  (`_RETURN_QUANT`) — przy 4 miejscach ruch o 3 punkty bazowe tracił cyfrę znaczącą
  i seria spłaszczała się schodkowo na wykresie.
- Nadpisanie `value_pln` za istniejący dzień przy niezmienionej liczbie wierszy (powtórka
  joba EOD za ten sam dzień) nie unieważnia klucza — zostaje na TTL, ten sam kompromis
  co w kroku 31.

## Krok 42 — benchmark (ZROBIONY 2026-08-15, commit `6db8138`)

`GET /portfolios/{id}/performance?benchmark=WIG20|^GSPC` dokłada drugą serię znormalizowaną
do 100, obie przeliczone na PLN. Silnik wyrównania i normalizacji siedzi w
`analytics/benchmark.py` jako funkcje czyste (14 testów jednostkowych), orkiestracja
w `service.py`, kontrakt opisany w `docs/api-kontrakt.md`. Frontend:
`/portfolios/{id}/wyniki` + `PerformanceChart.tsx`, wejście z dashboardu
(„Zobacz wyniki na tle rynku"). 9 testów integracyjnych na parametrze.

**Dziedzina parametru zamknięta** (`WIG20`, `^GSPC`) — 422 na cokolwiek innego. Otwarta
byłaby obietnicą, że każde aktywo ze słownika ma historię nadającą się na benchmark; nie ma
(samo `WIG20` w `prices` ma trzy notowania).

**`key` ≠ `symbol` dla GPW** (decyzja 8): użytkownik prosi o WIG20, liczy to `ETFBW20TR`.
`approximate: true` + `note` idą do UI, bo ETF śledzi Total Return i ma opłatę ok. 0,5%
rocznie — to jest przybliżenie i ma być tak oznaczone (CLAUDE.md #3.15).

**Wyrównanie kalendarzy przez `as_of`**, bez interpolacji. Brak notowania lub kursu NBP
w dniu startu ⇒ `unavailable_reason`, nigdy cichy mnożnik 1.

### Code-review kroku 42 (2026-08-15) — zero blokujących, znaleziska ZAMKNIĘTE

Izolacja (`PortfolioDep`), `close_adj`, `max(date) <= D` dla NBP, `Decimal` w całości
i ujawnione przybliżenie — potwierdzone przy recenzji. Siedem znalezisk naprawionych
tego samego dnia (`aebb008`):

1. ✅ **`benchmark_marker` powtarzał błąd naprawiony dla `valuations_marker`.** Marker był
   samym `MAX(prices.date)`, a notowania benchmarku przybywają **też wstecz** (`make backfill`
   dopisuje ~1251 sesji `ETFBW20TR.WA` nie ruszając maksimum, bo dzisiejszy wiersz zwykle
   już jest). Odpowiedź z `unavailable_reason` wisiała w cache przez 6 h TTL mimo że
   historia już była. Naprawa: `marketdata.repository.price_marker_for_asset` zwraca
   `MAX(date)` **i** `COUNT(*)`.
2. ✅ **Marker nie obejmował kursów FX.** Dla `^GSPC` nowy kurs NBP bez nowego notowania
   nie unieważniał klucza — a to stan codzienny, nie skrajny: NBP publikuje ok. 12:00,
   ingestia notowań chodzi wieczorem, więc świeże notowanie potrafi przez chwilę wisieć
   na wczorajszym kursie. Naprawa: `get_latest_fx_rate_date` jako trzeci segment markera,
   tylko dla benchmarku spoza PLN.
3. ✅ **Brak testu izolacji na nowym parametrze.** Sparametryzowany harness
   w `tests/test_isolation.py` przechodzi trasy po `app.routes` i nie dokłada query
   stringów, więc wariant `?benchmark=` nie był przejeżdżany. Dopisany jawny przypadek:
   użytkownik B pyta o cudzy portfel z `?benchmark=WIG20` → 404, bez wycieku treści.
4. ✅ **Komunikat operacyjny szedł do UI** — „uruchom `make seed`" renderowało się
   użytkownikowi, który nie ma jak tego zrobić. Rozdzielone: użytkownik dostaje
   „Porównanie z {label} jest chwilowo niedostępne", instrukcja idzie w `logger.error`.
5. ✅ **`alignBenchmark` wołane w `map` po wierszach** — O(n²), ~1,7 mln operacji przy
   `range=max`. Liczone raz w `useMemo` i podawane zarówno do wykresu, jak i do tabeli.
6. ✅ **`outperformance` liczone na `number` we froncie.** Przeniesione na backend
   (`_outperformance`, `Decimal`, string w JSON) — to liczba pokazywana użytkownikowi,
   więc CLAUDE.md §8 obowiązuje. Backend sprawdza przy okazji zgodność ostatnich dat obu
   serii zamiast ją zakładać; rozjazd daje `null`, nie liczbę z dwóch różnych dni.
7. ✅ **Brak testu na oznaczenie danych przybliżonych.** `vitest.config.ts` świadomie nie
   ma jsdom/RTL (render pokrywa Playwright), więc decyzja prezentacyjna wyszła
   z komponentu do czystej funkcji `benchmarkNotice` w `lib/performance.ts` — dokładnie
   ten przypadek, który komentarz w konfiguracji przewiduje. Pięć testów, w tym
   pierwszeństwo „brak serii" nad „dane przybliżone" i to, że brak `note` **nie** ucisza
   flagi `approximate` (poprzednia wersja komponentu w tym przypadku nie pokazywała nic).

Drobne zamknięte: `currency: null` zamiast pustego stringa (i w kontrakcie API),
nieosiągalna gałąź w `benchmark.py` opisana zamiast usuniętej, `test_real_benchmark_mapping`
przeniesiony do `tests/unit/test_benchmark_mapping.py` jako test kontraktu produktowego,
„pkt" → „p.p." w etykiecie, jedno `get_asset_by_symbol` zamiast dwóch na ścieżce żądania.

**Świadomie zostawione:**
- **Alias `date_`** (`service.py`, `schemas.py`) zamiast sugerowanego `import datetime as dt`.
  Powód istnienia dopisany w komentarzu; sama zamiana dotknęłaby każdej adnotacji `date`
  w obu plikach, czyli byłaby churnem większym niż problem.
- **Domyślny benchmark `WIG20`** także dla portfela czysto amerykańskiego. To decyzja
  produktowa (co pokazać przy wejściu na ekran), nie usterka — do rozstrzygnięcia razem
  z krokiem 41, gdy dojdzie beta i wybór benchmarku zacznie znaczyć więcej.

**Bramka po naprawie:** 422 testy backendu (było 417), 63 frontendu (było 61),
ruff/mypy/`next build` zielone. Obie regresje cache zweryfikowane odwrotnie: po cofnięciu
nowych segmentów markera dwa nowe testy padają.

### Code-review kroku 46 (2026-08-15) — dwa blokujące NAPRAWIONE

Izolacja, migracje, blokady doradcze i oznaczanie `heuristic` w UI — w porządku. Dwa
blokujące zamknięte tego samego dnia:

1. ✅ **Stored XSS na `href` newsa** (`components/news/NewsFeedPanel.tsx`). `item.url`
   pochodzi w całości z niezaufanego feedu, a React **nie** blokuje `javascript:`/`data:`
   w `href` — wypisuje ostrzeżenie w konsoli i renderuje link, więc jeden wpis w przejętym
   feedzie wydawcy wystarczał do wykonania skryptu w zalogowanej sesji.
   Naprawa: `is_safe_http_url` w `news/providers/base.py` (allowlist `http`/`https`,
   odrzucenie znaków sterujących **przed** parsowaniem — `"java\nscript:"` przechodzi przez
   `urlsplit` jako ścieżka względna, a w `href` wykonuje się jako `javascript:`), wpięta
   we wszystkich trzech providerach; wpis z niebezpiecznym adresem jest pomijany tak samo
   jak wpis bez daty. Druga linia obrony we froncie: `isSafeHttpUrl` w `lib/news.ts`,
   przy `false` tytuł renderuje się bez linku i z wyjaśnieniem, zamiast znikać po cichu.
   Pokrycie: `tests/unit/test_news_url_safety.py` (18 przypadków, każdy provider osobno
   + kontrole pozytywne). Zweryfikowane odwrotnie: po cofnięciu walidacji w providerach
   trzy testy padają, co potwierdza, że nie przechodzą przypadkiem.
2. ✅ **Sentyment ginął dla newsów już obecnych w bazie.** `upsert_news` robi
   `ON CONFLICT DO NOTHING`, więc gdy artykuł przyszedł wcześniej z Finnhuba (te same
   tickery są zamapowane na `alphavantage` w `db/seed.py`), `ingest_news_sentiment`
   podnosił tylko `match_confidence`, a `sentiment` i `sentiment_source` wyrzucał.
   `?with_sentiment_only=true` pokazywał wtedy pustkę, a UI mówiło „nikt tego nie ocenił" —
   przekłamanie z gatunku tych, przed którymi broni #3.15, tylko odwrócone.
   Naprawa: `repository.fill_missing_sentiment` — `UPDATE ... WHERE id = :id AND
   sentiment IS NULL`, wołane z `_store` gdy duplikat przyszedł z oceną. Warunek jest
   w SQL-u, nie w Pythonie, bo rozstrzygnąć go ma baza, a nie wyścig dwóch workerów.
   Licznik `sentiment_filled` w logu przebiegu — przy zerze przez kilka przebiegów widać,
   że job sentymentu nie robi nic poza podnoszeniem pewności.
   Pokrycie: dwa testy integracyjne (ocena dojeżdża; ocena już zapisana nie jest
   nadpisywana).

**Bramka po naprawie:** 417 testów backendu (było 397), 61 frontendu (było 50),
ruff/mypy/`next build` zielone.

Ważne (nieblokujące): cały przebieg joba w jednej transakcji trzymanej przez czas ruchu
sieciowego (`ingest_news.py:128-197`, `215-273`) — połączenie wisi `idle in transaction`,
a wyjątek na ostatnim symbolu kasuje dorobek całego przebiegu; limit **dobowy** Alpha Vantage
(25) nie jest nigdzie egzekwowany, chroni go wyłącznie interwał harmonogramu — powinien być
licznik w Redisie; `test_rss_provider.py` pokrywa tylko `_plain_text`, brak testów `bozo`,
pustego feedu, wpisu bez daty i całego `_store`; `content_hash` UNIQUE globalnie zwija dwie
różne depesze o tym samym tytule i **przypina do pierwszej obce aktywa** (przy tytułach
w rodzaju „Podsumowanie sesji na GPW") — do hasha warto włączyć host wydawcy.

Drobne: podwójne zużycie tokenów limitera (`GuardedNews` owija provider, który ma już
własny limiter), `finnhub_news` używa innego wiadra niż `finnhub` z `marketdata` mimo
wspólnego konta, `sentimentTone` renderuje `NaN` jako „wydźwięk neutralny", brak górnego
ograniczenia `published_at` (data z przyszłości przykleja się na szczycie feedu na zawsze),
domyślne adresy trzech żywych feedów wpisane w kod.

## Krok 47 — kalendarz dywidend (ZROBIONY 2026-08-23)

**Co powstało:** `dividend_events` + migracja `c03ad7b7217b`
(`20260823_dividend_events.py`) · `modules/dividends/` (`models`, `providers/base`,
`providers/alphavantage_dividends`, `repository`, `service`, `schemas`, `routes`) ·
`worker/jobs/ingest_dividends.py` + job dobowy w `worker/scheduler.py` (5:15 UTC) ·
frontend: `lib/dividends.ts` (+ testy), `components/dividends/DividendCalendarPanel.tsx`,
`app/portfolios/[id]/dywidendy/page.tsx`, wejście z dashboardu portfela ·
`docs/api-kontrakt.md` (sekcja „Dywidendy"), `docs/model-danych.md`.

### Zmiana dostawcy wymuszona przez rzeczywistość — Finnhub → Alpha Vantage

Plan kroku 47 mówił „Finnhub dla zagranicy". `GET /stock/dividend?symbol=AAPL` zwraca
na darmowym planie `403 {"error":"You don't have access to this resource."}` — sprawdzone
2026-08-23 realnym kluczem produkcyjnym, ten sam wynik co `/news-sentiment` w kroku 46.
Zakres kroku bez zmian, zmienia się wyłącznie źródło: Alpha Vantage `function=DIVIDENDS`
jest w darmowym planie i oddaje komplet czterech dat (`ex_dividend_date`,
`declaration_date`, `record_date`, `payment_date`) plus kwotę na akcję.

**GPW nadal nie jest pokryta — zgodnie z tym, co plan przewidywał jako ograniczenie.**
Alpha Vantage dla `PKN.WAR` oddaje `{"symbol": "PKN.WAR", "data": []}`, czyli odpowiedź
**nie do odróżnienia od „spółka nie płaci dywidendy"**. Dlatego pokrycie rozstrzyga
mapowanie `asset_source_map` (provider `alphavantage_dividends`), a nie obecność zdarzeń w bazie:
aktywo bez mapowania jest raportowane jako **nieobjęte** (`assets_without_coverage`,
`uncovered_markets`), a nie jako „bez dywidend" (CLAUDE.md #3.15). UI pokazuje tę notę
**nad** listą i także wtedy, gdy lista nie jest pusta.

### Decyzje przy implementacji

- **`ON CONFLICT DO UPDATE`, odwrotnie niż przy newsach.** Treść opublikowanej depeszy
  jest niezmienna, zapowiedziana dywidenda — nie: kwota i data wypłaty bywają korygowane
  przed wypłatą, więc świeższa odpowiedź dostawcy wygrywa. Klucz naturalny
  `UNIQUE (asset_id, ex_date)`.
- **Bez przeliczania na PLN i bez podatku.** Kurs właściwy dla wypłaty to kurs z dnia
  poprzedzającego wypłatę, czyli z przyszłości — liczba w PLN pokazana dziś byłaby
  prognozą udającą wycenę. Podatek u źródła i rozliczenia to Etap 21 (CLAUDE.md §22);
  `dividend_events` świadomie nie ma `user_id` ani niczego, co dałoby się pomylić
  z wpisem księgowym.
- **`estimated_gross` = kwota × DZISIEJSZA ilość** — UI nazywa to szacunkiem, nie
  należnością.
- **Okno kalendarza zaczyna się dziś.** Wczorajsza ex-data jest już nie do złapania,
  a pokazana wśród „nadchodzących" sugerowałaby, że da się z nią coś zrobić. Job zapisuje
  jednak także historię (dostawca oddaje ją w tej samej odpowiedzi, więc nie kosztuje
  dodatkowego zapytania) — filtr po dacie jest po stronie odczytu.
- **Budżet 25 zapytań/dobę jest ograniczeniem pierwszej klasy.** Job dobowy (`CronTrigger`
  5:15 UTC, nie interwał — interwał liczyłby się od startu workera, więc restart
  przesuwałby porę), pyta wyłącznie o aktywa, które ktokolwiek **trzyma**, i bierze
  najwyżej 8 symboli na przebieg (`_MAX_SYMBOLS_PER_RUN`), zostawiając zapas jobowi
  sentymentu z kroku 46 (12 przebiegów/dobę).
- **Brak wpisu w nawigacji globalnej.** `NAV_ITEMS` ma pięć pozycji i to sufit dolnego
  paska na 375 px (komentarz w `components/nav/navItems.ts`); szósta wymaga przebudowy
  paska, czyli zmiany poza zakresem tego kroku. Wejście prowadzi z dashboardu portfela,
  tak jak do struktury, wyników i rynków.

### Weryfikacja

- `ruff format --check`/`ruff check`/`mypy app` (strict, 76 plików) zielone.
- Backend: **442 passed** (435 poprzednich + 7 nowych integracyjnych), plus 7 nowych
  jednostkowych dla providera. Harness izolacji **automatycznie objął nową trasę**:
  `test_user_b_cannot_touch_user_a_resources[['GET']:/api/portfolios/{portfolio_id}/dividends]`.
- Frontend: `npm run lint`, `tsc --noEmit`, Vitest **68 passed** (63 poprzednich + 5 nowych w `lib/dividends.test.ts`),
  `next build` — trasa `/portfolios/[id]/dywidendy` w wykazie.
- **Żywa weryfikacja na dev:** job pobrał **57 zdarzeń dla AAPL** (historia od 2012-08-09,
  ostatnia ex-data 2026-08-10) i zapisał je idempotentnie; MSFT w tym samym przebiegu
  padł na dobowym limicie Alpha Vantage i **nie przerwał joba**
  (`failed_symbols=1 stored=57`) — dokładnie zachowanie z reguły 6 skilla `job-eod`.
  `GET /portfolios/{id}/dividends?horizon_days=365` na portfelu demo zwraca pustą listę
  z `assets_covered=2`, `assets_without_coverage=["CDR","PKN","bitcoin"]` i
  `uncovered_markets=["CRYPTO","GPW"]` — pustka jest **prawdziwa** (następna ex-data AAPL
  nie jest jeszcze ogłoszona) i opisana, a nie milcząca.

### Zostaje po kroku 47 (nieblokujące)

- **Kalendarz pokazuje dziś pustkę nawet dla pokrytych spółek**, bo Alpha Vantage podaje
  wyłącznie dywidendy **już ogłoszone** — między wypłatami nie ma czego pokazać. To
  poprawne zachowanie, ale warto po kilku tygodniach sprawdzić, jak często ekran jest
  pusty przy realnym portfelu, zanim krok 50 oprze na nim powiadomienie push (decyzja 3
  planu etapu 9: push o zbliżającej się ex-dacie).
- **Brak dostawcy dla GPW.** Do rozważenia w Etapie 22 (jakość danych): komunikaty ESPI
  albo strony relacji inwestorskich jako źródło ex-dat dla polskich spółek. Dziś rynek
  z największą liczbą pozycji jest poza kalendarzem i tylko o tym informujemy.
- **`_MAX_SYMBOLS_PER_RUN = 8` przy stałej kolejności po `provider_symbol`** — przy
  portfelu z więcej niż 8 mapowanymi aktywami symbole z końca alfabetu nie doczekają się
  odświeżenia. Rotacja po `MIN(fetched_at)` byłaby uczciwsza; nie zrobiona, bo dziś
  mapowanych aktywów jest 2.
- Brak podkomendy CLI (`python -m app.cli ingest-dividends`) — tak samo jak przy newsach
  z kroku 46; ręczne uruchomienie idzie przez `python -c`.

### Poprawki po code-review kroku 47 (2026-08-26)

Cztery znaleziska **blokujące** i dwa „do poprawy" zamknięte:

1. **Klucz API wyciekał komunikatem wyjątku HTTP** (`marketdata/providers/http_client.py`).
   `httpx` wkleja pełny URL — razem z `apikey=` — do treści `HTTPStatusError`, a ten
   trafia do logu i do Sentry przy każdym statusie != 2xx. Naprawione **u przyczyny**,
   w `get_with_backoff`: URL jest odtwarzany z sekretami zamienionymi na `***`
   (`apikey`, `apiKey`, `api_key`, `token`, `auth_token`), reszta query stringu zostaje.
   To naprawia jednocześnie dostawców z kroku 46 (`alphavantage_news`, `finnhub_news`),
   którzy mieli ten sam problem. Zweryfikowane, że nikt poza `auth/service.py` nie łapie
   `HTTPStatusError`, więc podmiana obiektu nie zmienia niczyjej logiki.
   Test: `tests/unit/test_http_client_redaction.py`.
2. **Padnięty symbol kasował dane całego przebiegu** (`worker/jobs/ingest_dividends.py`).
   `_ingest_symbol` łapał wyłącznie `ProviderUnavailableError` (a `get_with_backoff`
   wypuszcza `httpx.HTTPStatusError` wprost), a commit był jeden, na końcu przebiegu —
   więc awaria ósmego symbolu unieważniała sesję i wyrzucała siedem udanych pobrań,
   czyli spalony dobowy budżet bez zapisu. Teraz: commit **po każdym symbolu**,
   `rollback()` + `logger.exception` w gałęzi błędu, łapanie szerokie.
   Test: `tests/integration/test_ingest_dividends_job.py` (fake provider, jeden symbol
   rzuca, drugi zapisuje).
3. **`NaN`/`Infinity` w kwocie wywracały cały symbol** (`alphavantage_dividends.py`).
   `Decimal("NaN")` powstaje bez błędu, ale `Decimal("NaN") <= 0` rzuca
   `InvalidOperation` — kontrola skończoności musi iść **przed** porównaniem. Dołożony
   też górny limit `1e12` (pojemność `NUMERIC(20,8)`): większa kwota wysadziłaby dopiero
   `INSERT`. Testy rozszerzone o `"NaN"`, `"Infinity"`, `"1e12"`.
4. **Rozdzielone mapowanie dostawców.** `DIVIDEND_PROVIDER` było `"alphavantage"`, czyli
   ten sam klucz `asset_source_map` co job sentymentu z kroku 46 — każde aktywo zmapowane
   dla newsów kalendarz raportował jako „pokryte dywidendowo" i odwrotnie, mimo że to dwie
   różne funkcje API o różnym pokryciu rynków. Teraz `"alphavantage_dividends"`, z własnymi
   wierszami w `db/seed.py`; `docs/api-kontrakt.md` zaktualizowany.
5. **`estimated_gross` kwantyzowany do 8 miejsc** (`ROUND_HALF_UP`). Mnożenie `Decimal`
   sumuje skale czynników, więc endpoint zwracał `"2.7000000000000000"` zamiast
   obiecanego kontraktem `"2.70000000"`. Test sprawdza dokładny string, nie wartość.

**Weryfikacja:** `ruff format`/`ruff check`/`mypy` (strict, 98 plików) zielone, backend
**517 passed** (w tym 5 nowych: 3 redakcji URL, 2 odporności joba) — czerwone zostaje
wyłącznie znane 10 testów `test_isolation.py` z niedokończonego kroku 43
(`KeyError: 'tag_id'`/`'watchlist_id'`), niezwiązane z tymi poprawkami. Frontend:
Vitest **77 passed**, `tsc --noEmit` czysty (frontend nietknięty w tej partii).

**Zostaje jako nieblokujące** (poza powyższą listą z kroku 47):

- Nowy dostawca nie jest owinięty w `Guarded`/`CircuitBreaker` (job idzie prosto do
  providera), a jego `RateLimiter` używa klucza `alphavantage_dividends`, czyli **innego
  wiadra niż job newsowy**, mimo wspólnego konta i wspólnego limitu 25/dobę. To samo
  znalezisko co przy `finnhub_news` w kroku 46 — do domknięcia razem.
- `repository.list_covered_asset_ids` nie filtruje `AssetSourceMap.is_active`.
- Klasy aktywów, które z definicji nie płacą dywidend (krypto), trafiają na listę
  „bez pokrycia" — formalnie prawda, ale zaszumia komunikat.
- Sumowanie ilości po `asset_id` w `service` jest martwe (`uq_holdings_portfolio_asset`
  gwarantuje jeden wiersz), a komentarz obok twierdzi inaczej.
- `SOON_DAYS` jako stała w komponencie, `today` liczone przy każdym renderze,
  brak testu `horizon_days=0/366 → 422`.
