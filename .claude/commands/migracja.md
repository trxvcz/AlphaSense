---
description: Przygotuj i zweryfikuj migrację Alembic
argument-hint: <opis zmiany schematu>
---

Zmiana schematu: **$ARGUMENTS**

Deleguj do subagenta `db-migrator`:

1. Zaktualizuj modele SQLAlchemy zgodnie z `docs/model-danych.md`.
2. Jeśli zmiana jest łamiąca (usunięcie kolumny z danymi, zmiana typu) — **zatrzymaj się i zapytaj mnie**.
3. `make revision m="..."`, potem przeczytaj wygenerowany plik i popraw: precyzja `NUMERIC(20,8)`, indeksy, `CHECK`, `ON DELETE CASCADE`, kolejność operacji.
4. Napisz sensowny `downgrade()`.
5. Przetestuj: `make migrate` → `alembic downgrade -1` → `make migrate`.
6. Zaktualizuj `docs/model-danych.md`.
7. Pokaż mi diff migracji i wyjaśnij, co się zmienia w danych.
