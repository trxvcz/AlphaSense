---
description: Zapisz nową decyzję architektoniczną
argument-hint: <temat decyzji>
---

Zapisz ADR na temat: **$ARGUMENTS**

1. Sprawdź `docs/adr/`, jaki jest następny wolny numer (seria 1xx dla v2).
2. Utwórz `docs/adr/ADR-1xx-<slug>.md` według szablonu `docs/adr/_szablon.md`.
3. Wypełnij: kontekst, rozważane opcje (tabela: opcja / złożoność / zachowanie), decyzja, konsekwencje (+ / − / do rewizji).
4. Bądź uczciwy w minusach — ADR bez minusów to marketing, nie decyzja.
5. Dopisz wpis do `docs/adr/README.md` (indeks).
6. Jeśli decyzja wymaga mojej akceptacji, ustaw status „Proponowana" i dodaj ją do sekcji „Decyzje oczekujące" w `../../../STATUS.md`.
