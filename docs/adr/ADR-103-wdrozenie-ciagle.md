# ADR-103: Wdrożenie ciągłe z GitHub Actions zamiast ręcznego runbooka

**Status:** Proponowana
**Data:** 2026-08-05
**Dotyczy etapów:** 7 (kroki 36–39), pośrednio każdy kolejny krok, który trafia na produkcję

## Kontekst

Plan etapu 7 uzgodniony 2026-07-28 zawierał decyzję 4: *„Zakres na VPS: tylko pliki i runbook.
Przygotowuję `Caddyfile`, compose produkcyjny, Dockerfile'e, skrypty i `docs/wdrozenie.md`; samo
wdrożenie wykonuje użytkownik."* Kroki 36–38 zostały zrobione dokładnie w tym modelu.

Po ich zamknięciu w drzewie roboczym pojawił się job `deploy` w `.github/workflows/ci.yml`, który
po zielonym pushu na `main` łączy się po SSH z VPS-em i wykonuje `make prod-build`, `prod-up`
i `prod-seed`. To jest zmiana modelu wdrożenia, a nie szczegół implementacyjny, więc wymaga
zapisanej decyzji (CLAUDE.md §4.5 i §10).

Fakty, które wymuszają rozstrzygnięcie:

- Ręczna aktualizacja z runbooka (§8) to pięć poleceń wykonywanych po SSH. Nic ich nie pilnuje:
  pominięty `prod-build` albo `prod-seed` po zmianie słownika rynków daje produkcję niezgodną
  z zacommitowanym kodem, a `worker/scheduler.py` czyta `markets` raz przy starcie (ADR-102).
- CI ma trzy joby (`backend`, `frontend`, `obrazy-prod`), ale **nie ma testów e2e** — Playwright
  wymaga żywego stacku. Zielony pipeline nie dowodzi, że aplikacja działa jako całość.
- `GET /api/health` z założenia **zawsze zwraca HTTP 200** (krok 37), o stanie mówi ciało. Każde
  sprawdzenie oparte na kodzie HTTP jest tu bezużyteczne, a wygląda na zabezpieczenie.
- Konto zdolne uruchomić `make prod-*` musi mieć dostęp do gniazda Dockera, czyli jest
  równoważne rootowi na maszynie, na której leży `.env.prod` (SECRET_KEY, hasło Postgresa,
  `GOOGLE_CLIENT_SECRET`, klucz do bucketu B2 z prawem kasowania kopii).

## Rozważane opcje

| Opcja | Złożoność | Zachowanie |
|---|---|---|
| A. Zostaje ręczny runbook (decyzja 4 bez zmian) | zero | Zero nowej powierzchni ataku. Każde wdrożenie zależy od tego, czy człowiek wykonał wszystkie kroki i w tej kolejności. |
| B. CD z kluczem SSH ogólnego przeznaczenia | mała | Wygodne. Klucz w GitHubie pozwala wykonać na VPS-ie **dowolne** polecenie jako root — wystarczy zmiana `ci.yml` na `main` albo przejęcie konta GitHub. |
| C. CD z kluczem ograniczonym do jednego skryptu (`command=`/`restrict`), bramka i weryfikacja po stronie VPS-a | średnia | Klucz umie wywołać wyłącznie `infra/deploy.sh` i przekazać mu jeden argument — SHA. Skrypt sam sprawdza, że commit jest w `origin/main`, wdraża, weryfikuje stan i wycofuje się przy niepowodzeniu. |

## Decyzja

**Opcja C.** Decyzja 4 etapu 7 zostaje zmieniona: wdrożenie na produkcję jest automatyczne po
zielonym pushu na `main`, ale GitHub Actions nie dostaje powłoki na VPS-ie — dostaje jeden
parametr do jednej operacji. Autorytetem jest skrypt w repozytorium na serwerze
(`infra/deploy.sh`), nie treść polecenia przysłana przez klienta SSH.

Sprawdzenie po wdrożeniu **parsuje ciało** `/api/health` (`status == "ok"` i `db == "up"`)
i ponawia próbę, zamiast wnioskować z kodu HTTP.

## Konsekwencje

- (+) Produkcja zawsze odpowiada konkretnemu commitowi z `main`, który przeszedł CI. `APP_VERSION`
  ustawia się sam na SHA, więc `release` w Sentry i `version` w `/api/health` przestają kłamać.
- (+) Nieudane wdrożenie wraca na poprzedni commit i mówi o tym czerwonym jobem, zamiast zostawiać
  produkcję w stanie pośrednim.
- (+) Kompromitacja konta GitHub nie daje wykonania dowolnego kodu na VPS-ie — daje możliwość
  wdrożenia commita, który i tak jest w `origin/main`.
- (−) Nowa powierzchnia ataku mimo wszystko istnieje: kto może wypchnąć na `main`, ten wdraża na
  produkcję. Ochroną jest branch protection na `main`, nie ten ADR.
- (−) Dwa nowe miejsca do utrzymania: `infra/deploy.sh` na serwerze i sekrety w GitHubie
  (`SSH_PRIVATE_KEY_ALPHASENSE`, `SSH_KNOWN_HOSTS`, `SSH_HOST`, `SSH_PORT`, `SSH_USER`).
- (−) Wdrożenie zaczyna się dziać bez człowieka patrzącego na wynik. Dopóki `make smoke` nie jest
  częścią tej ścieżki, jedynym dowodem poprawności jest `/api/health` — czyli „proces żyje i widzi
  bazę", a nie „produkt działa".
- (do rewizji) Gdy `make smoke` (krok 39) da się uruchomić po wdrożeniu — wtedy to on, a nie
  `/api/health`, powinien decydować o wycofaniu. Do rewizji także wtedy, gdy pojawi się drugie
  środowisko (staging): wdrażanie prosto z `main` na produkcję ma sens dokładnie dopóty, dopóki
  środowisko jest jedno.
