---
description: Ustal i wykonaj następny krok z planu działania
argument-hint: [opcjonalnie numer kroku]
---

Wykonaj następny krok projektu.

1. Przeczytaj `../../../STATUS.md` i ustal pierwszy niezrobiony krok (albo krok `$1`, jeśli podano numer).
2. Przeczytaj odpowiedni fragment `docs/plan-dzialania-portfel-v2.md` oraz powiązane sekcje `docs/projekt-systemu-portfel-v2.md`.
3. Sprawdź, czy krok nie jest zablokowany przez niezatwierdzoną decyzję z sekcji „Decyzje oczekujące" w `../../../STATUS.md`. Jeśli jest — przedstaw decyzję do podjęcia i zatrzymaj się.
4. Rozpisz plan w TODO i pokaż go, zanim zaczniesz pisać kod. Jeśli krok jest większy niż dzień pracy — podziel go i zaproponuj podział.
5. Wykonaj, delegując do właściwego subagenta (backend-fastapi / frontend-next / data-provider / db-migrator / devops).
6. Uruchom `make check`.
7. Zaktualizuj `../../../STATUS.md`: zaznacz krok, dopisz wiersz w dzienniku sesji.
8. Podsumuj w trzech punktach: co zrobione, co dalej, co wymaga mojej decyzji.
