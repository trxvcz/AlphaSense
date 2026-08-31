# Konwencje projektu

## Python

- ruff (format + lint), mypy strict dla `app/modules/` i `app/core/`
- Typy wszędzie, także w testach. `Any` wymaga komentarza z uzasadnieniem.
- Nazwy: tabele i kolumny `snake_case` liczba mnoga dla tabel; klasy ORM w liczbie pojedynczej.
- Wyjątki domenowe w `core/errors.py`. `HTTPException` wolno rzucać wyłącznie w warstwie routes lub w handlerze.
- Konfiguracja przez `pydantic-settings`, jedno źródło w `core/config.py`. Zero `os.getenv` rozsianego po kodzie.
- Logowanie strukturalne (`structlog`), nigdy `print`. Nigdy nie loguj tokenów, haseł, e-maili w całości.

## TypeScript

- Brak `any`. `strict: true`.
- Komponenty: `PascalCase.tsx`, hooki `useCoś.ts`, funkcje pomocnicze `camelCase.ts`.
- Kwoty ze stringów formatowane przez `lib/money.ts`. Zero obliczeń finansowych na froncie.
- Klasy Tailwind, bez CSS-in-JS. Kolory z tokenów, nie hexy w komponentach.

### Teksty interfejsu (i18n, krok 50)

- **Nowy tekst widoczny dla użytkownika idzie do `messages/pl.json`**, nie do JSX. Polski jest
  jedynym językiem; katalog istnieje po to, żeby drugi był dopisaniem pliku, a nie przepisywaniem
  komponentów.
- Przestrzenie nazw idą **za obszarem, nie za komponentem** (`nav`, `offline.banner`,
  `offline.page`) — ten sam tekst bywa użyty w dwóch miejscach, komponenty się zmieniają.
- Server Component: `await getTranslations("przestrzeń")` z `next-intl/server`.
  Client Component: `useTranslations("przestrzeń")`.
- **Logika zwraca klucz i parametry, nie gotowe zdanie** (wzorzec: `lib/offline/bannerText.ts`).
  Dzięki temu „co pokazać" zostaje testowalne bez przeglądarki, a „jakimi słowami" mieszka
  w katalogu. Odmiana i przyimki należą do komunikatu, nie do sklejania stringów w kodzie.
- **Nie ma segmentu `[locale]` w URL** i przy jednym języku nie będzie — patrz `lib/i18n.ts`.
- Migracja istniejących ekranów jest **stopniowa**: krok 50 przeniósł nawigację i tryb offline,
  reszta idzie przy okazji dotykania danego widoku. Nie rób osobnego przebiegu „przenieś
  wszystkie stringi" — to zmiana bez testowalnego efektu, za to z dużym diffem.

## Testy

| Rodzaj | Gdzie | Zasada |
|---|---|---|
| jednostkowe | `tests/unit/` | logika obliczeniowa na znanych liczbach, bez bazy i bez mocków ORM |
| integracyjne | `tests/integration/` | endpoint + prawdziwa baza testowa (Postgres w kontenerze) |
| izolacji | `tests/test_isolation.py` | parametryzowany, po wszystkich trasach — zielony zawsze |
| dostawców | `tests/providers/` | nagrane odpowiedzi, zero sieci; realne API pod markerem `network` |

Nie piszemy testów asertujących, że kod robi to, co robi. Test ma opisywać wymaganie: „dzień zmiany składu nie tworzy zwrotu", „suma wag alokacji równa 1".

## Git

- Commity konwencjonalne: `feat(analytics): ranking rynków wg wagi`, `fix(marketdata): cofanie kursu NBP na święta`.
- Zakresy: `auth`, `portfolio`, `marketdata`, `analytics`, `news`, `frontend`, `worker`, `infra`, `docs`.
- Jeden krok z planu = jeden lub kilka commitów, nie odwrotnie.
- Treść commita po angielsku lub polsku — ale konsekwentnie w całym repo.

## Dokumentacja

Zmiana schematu → `docs/model-danych.md`. Nowy endpoint → `docs/api-kontrakt.md`. Decyzja architektoniczna → `docs/adr/`. Ukończony krok → `../../STATUS.md`. Bez tego krok nie jest ukończony.

## Nazewnictwo domenowe (używaj konsekwentnie)

| Polski | Kod |
|---|---|
| pozycja | `holding` (nigdy `transaction`, nigdy `position` — kolizja pojęć) |
| wycena | `valuation` |
| snapshot dzienny | `portfolio_valuation` |
| rynek / giełda | `market` |
| indeks referencyjny | `reference index` / `index_asset` |
| klasa aktywa | `asset_class` |
| koncentracja | `concentration` |
| zmiana składu | `composition_change` |
