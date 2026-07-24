# ADR-002: Izolacja danych między użytkownikami

**Status:** Zaakceptowana (przeniesiona z v1), część RLS do wykonania w Fazie 2
**Data:** 2026-07-20
**Dotyczy kroków:** 14, 15, 44

## Decyzja

Trzy warstwy obrony:

1. **Zależność aplikacyjna** (od etapu 2, obowiązkowa): każdy endpoint pobiera zasób przez `get_owned_*`, nigdy przez surowe ID z path.
2. **Parametryzowany test dwóch użytkowników w CI** (od etapu 2): przechodzi automatycznie po wszystkich zarejestrowanych trasach; nowy endpoint jest pokryty bez pisania nowego testu.
3. **Row Level Security w Postgresie** (etap 44, Faza 2): polityki po `user_id`, sesja aplikacyjna ustawia `SET LOCAL app.user_id`, worker działa na roli z `BYPASSRLS`.

RLS nie zastępuje warstwy 1 — to obrona w głąb.

## Konsekwencje

- (+) najgroźniejsza klasa błędów jest wyłapywana systemowo, nie przez czujność
- (−) każdy nowy typ zasobu wymaga własnej zależności `get_owned_*` i wpisu w parametryzacji testu
- (−) RLS komplikuje debugowanie zapytań i wymaga dyscypliny w ustawianiu zmiennej sesyjnej

Procedura: skill `izolacja-danych`.
