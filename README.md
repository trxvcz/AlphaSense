# AlphaSense

Aplikacja do monitoringu i analizy składu portfela inwestycyjnego. Bez rejestru transakcji: wpisujesz co masz, aplikacja wycenia, rozkłada na czynniki i pokazuje rynki, na których jesteś zainwestowany.

## Szybki start

```bash
cp .env.example .env      # uzupełnij klucze API
make up                   # postgres, redis, api, frontend
make migrate
make seed                 # słownik rynków + aktywa demo
open http://localhost:3000
```

## Praca z Claude Code

Repozytorium jest przygotowane pod pracę agentową:

- `../CLAUDE.md` — kontekst i zasady projektu (czytane automatycznie)
- `../STATUS.md` — postęp: 50 kroków, dziennik sesji, decyzje oczekujące
- `.claude/agents` — wyspecjalizowani subagenci (backend, frontend, dane rynkowe, migracje, bezpieczeństwo, DevOps, review)
- `.claude/commands` — komendy: `/nastepny-krok`, `/etap`, `/endpoint`, `/migracja`, `/test-izolacji`, `/review`, `/adr`, `/deploy`, `/kontrola-zakresu`
- `.claude/skills` — powtarzalne procedury projektowe
- `docs` — projekt systemu, plan działania, ADR-y, kontrakt API, model danych

Typowa sesja: `claude` → `/nastepny-krok` → praca → `/review` → aktualizacja `../STATUS.md`.

## Dokumentacja

| Plik | Zawartość |
|---|---|
| `docs/projekt-systemu-portfel-v2.md` | projekt systemu |
| `docs/plan-dzialania-portfel-v2.md` | plan 50 kroków |
| `docs/adr` | decyzje architektoniczne |
| `docs/model-danych.md` | tabele, typy, indeksy |
| `docs/api-kontrakt.md` | endpointy i kształt odpowiedzi |
| `docs/konwencje.md` | konwencje kodu i testów |
| `docs/slownik-rynkow.md` | rynki + indeksy referencyjne |
