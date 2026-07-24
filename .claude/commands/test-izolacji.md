---
description: Zweryfikuj izolację danych między użytkownikami na wszystkich trasach
---

Uruchom pełną weryfikację izolacji danych (ADR-002).

1. Wypisz wszystkie trasy aplikacji (`app.routes`) przyjmujące identyfikator zasobu.
2. Dla każdej sprawdź, czy identyfikator przechodzi przez zależność `get_owned_*`. Wypisz trasy, które tego nie robią — to znaleziska krytyczne.
3. Uruchom parametryzowany test izolacji dwóch użytkowników: `pytest tests/test_isolation.py -v`.
4. Jeśli jakaś trasa nie jest pokryta testem — dopisz ją do parametryzacji.
5. Uruchom subagenta `security-auditor` na modułach auth i portfolio.
6. Raport: trasy niepokryte, testy nieprzechodzące, rekomendacja.

Ten test ma przechodzić w CI od etapu 2 do końca projektu. Jeśli czerwony — nic innego nie jest ważniejsze.
