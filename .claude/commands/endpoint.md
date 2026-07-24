---
description: Dodaj nowy endpoint API zgodnie z konwencjami projektu
argument-hint: <metoda i ścieżka, np. GET /portfolios/{id}/allocation>
---

Dodaj endpoint: **$ARGUMENTS**

Kolejność (deleguj do subagenta `backend-fastapi`):

1. Sprawdź `docs/api-kontrakt.md` — czy endpoint już jest opisany? Jeśli tak, trzymaj się opisanego kształtu. Jeśli nie, zaproponuj kontrakt i dopisz go tam.
2. Schematy Pydantic w `schemas.py` (kwoty jako `Decimal` → string w JSON).
3. Route: parametry ścieżki **wyłącznie** przez `Depends(get_owned_*)`. Jeśli brakuje odpowiedniej zależności — dodaj ją w `core/deps.py`.
4. Logika w `service.py`, zapytania w warstwie repozytorium.
5. Cache tylko jeśli odczyt jest kosztowny; klucz wersjonowany.
6. Testy: szczęśliwa ścieżka, walidacja wejścia, 401 bez tokenu, 403/404 dla cudzego zasobu.
7. Dopisz do parametryzowanego testu izolacji, jeśli to nowy typ zasobu.
8. `make check` i krótkie podsumowanie z przykładową odpowiedzią JSON.
