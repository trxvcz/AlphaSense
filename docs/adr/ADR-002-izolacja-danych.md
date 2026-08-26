# ADR-002: Izolacja danych między użytkownikami

**Status:** Zaakceptowana (przeniesiona z v1), **wszystkie trzy warstwy wdrożone** (RLS: krok 44, 2026-08-26)
**Data:** 2026-07-20
**Dotyczy kroków:** 14, 15, 44

## Decyzja

Trzy warstwy obrony:

1. **Zależność aplikacyjna** (od etapu 2, obowiązkowa): każdy endpoint pobiera zasób przez `get_owned_*`, nigdy przez surowe ID z path.
2. **Parametryzowany test dwóch użytkowników w CI** (od etapu 2): przechodzi automatycznie po wszystkich zarejestrowanych trasach; nowy endpoint jest pokryty bez pisania nowego testu.
3. **Row Level Security w Postgresie** (krok 44, wdrożone 2026-08-26): polityki po `user_id`, sesja aplikacyjna ustawia `SET LOCAL app.user_id`, worker działa na roli omijającej RLS.

RLS nie zastępuje warstwy 1 — to obrona w głąb.

## Jak działa warstwa 3 (doprecyzowane przy wdrożeniu)

**Dwie role, nie jedna.** API łączy się jako `portfel_app` (`DATABASE_URL_APP`): bez `SUPERUSER`, bez `BYPASSRLS` i **bez własności tabel** — jedno i drugie omija polityki milcząco, więc aplikacja połączona rolą właściciela miałaby RLS bez zębów, przy zielonej suicie. Migracje, worker i CLI zostają na roli właściciela (`DATABASE_URL`); w kodzie widać to jako `OwnerSessionLocal` obok `AsyncSessionLocal` (`app/db/session.py`).

**Kontekst przez `SET LOCAL`, ustawiany przy każdej transakcji.** Zwykłe `SET` przeżyłoby zwrot połączenia do puli i następne żądanie odziedziczyłoby cudze `app.user_id` — czyli dokładnie ten wyciek, przed którym RLS broni. Ustawienie transakcyjne znika przy `COMMIT`, a listener na zdarzeniu `begin` (`app/db/rls.py`) wpina je w każdą kolejną transakcję z `ContextVar` per żądanie. Jedno żądanie robi kilka transakcji (serwisy commitują same), więc jednorazowe ustawienie w `get_db` zniknęłoby po pierwszym commicie.

**Brak kontekstu = zero wierszy**, nie „wszystko": `NULLIF(current_setting('app.user_id', true), '')::uuid` daje `NULL`, a porównanie z `NULL` nie przepuszcza niczego.

**`users` i `refresh_tokens` bez polityk.** Rejestracja, logowanie i rotacja tokenu dzieją się, zanim istnieje `app.user_id` — polityka na tych tabelach zablokowałaby własne uwierzytelnianie. Ochrona zostaje na warstwie 1. Słowniki globalne (`assets`, `prices`, `markets`, `fx_rates`, `news`, `dividend_events`) polityk nie mają, bo nie mają właściciela-użytkownika.

**Kolejność wdrożenia:** `alembic upgrade head` (tworzy rolę bez hasła i bez `LOGIN`) → `make db-roles` (nadaje hasło z `DATABASE_URL_APP`; hasła nie ma w migracji, bo migracje są w repo) → restart API. Wycofanie: `alembic downgrade -1` zdejmuje polityki i **odblokowuje aplikację**, zostawiając rolę i nadania.

## Konsekwencje

- (+) najgroźniejsza klasa błędów jest wyłapywana systemowo, nie przez czujność
- (−) każdy nowy typ zasobu wymaga własnej zależności `get_owned_*` i wpisu w parametryzacji testu
- (−) RLS komplikuje debugowanie zapytań i wymaga dyscypliny w ustawianiu zmiennej sesyjnej

Procedura: skill `izolacja-danych`.
