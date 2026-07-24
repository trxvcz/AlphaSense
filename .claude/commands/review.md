---
description: Recenzja zmian przed commitem
---

Zrecenzuj bieżące zmiany.

1. `git status` i `git diff` (dla zmian zacommitowanych, ale niewypchniętych — `git diff origin/main...HEAD`).
2. Uruchom subagenta `code-reviewer`.
3. Jeśli zmiany dotykają auth, endpointów lub konfiguracji — uruchom też `security-auditor`.
4. `make check`.
5. Zbierz wyniki w jeden raport: **Blokujące / Do poprawy / Drobne**.
6. Jeśli nic blokującego — zaproponuj treść commita (konwencjonalną) i zapytaj, czy commitować.
