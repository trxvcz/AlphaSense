---
description: Rozpocznij lub podsumuj cały etap planu
argument-hint: <numer etapu 0-9>
---

Etap: **$1**

Jeśli etap jest niezaczęty — zaplanuj go:
1. Wypisz wszystkie kroki tego etapu z `docs/plan-dzialania-portfel-v2.md`.
2. Dla każdego: co konkretnie powstanie (pliki, endpointy, tabele, widoki), który subagent to robi, jakie ma zależności.
3. Wskaż ryzyka i miejsca, gdzie potrzebna jest moja decyzja.
4. Podaj kryterium ukończenia etapu — co ma działać na koniec.
5. Zapytaj o zgodę, zanim zaczniesz kodzić.

Jeśli etap jest w toku lub skończony — podsumuj: co zrobione, co zostało, czy kryterium ukończenia jest spełnione, i uruchom subagenta `code-reviewer` na zmianach z tego etapu.
