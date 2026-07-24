# ADR-102: Mapowanie rynków i indeksów referencyjnych

**Status:** Zatwierdzona (2026-07-24)
**Data:** 2026-07-20
**Dotyczy kroków:** 2, 17, 19, 23, 30, 34

## Kontekst

Funkcja „obserwuj rynki, na których inwestuję" wymaga przypisania aktywa do rynku oraz przypisania rynkowi indeksu referencyjnego. Niezależnie od tego harmonogram ingestii EOD i tak musi znać godziny zamknięcia poszczególnych giełd.

## Decyzja

Słownikowa tabela `markets` (kod, nazwa, `index_asset_id`, strefa czasowa, `eod_time`) utrzymywana przez system — kilkanaście wpisów. `assets.market_code` jest kluczem obcym do słownika. Indeksy referencyjne to zwykłe rekordy w `assets` (WIG20, ^SPX, ^NDX, DAX, BTC), pobierane tymi samymi jobami EOD. Ranking rynków to `GROUP BY market_code` po wycenionych pozycjach. **Godziny jobów EOD czytane z tego samego słownika** — jedno źródło prawdy o rynkach.

## Konsekwencje

- (+) „Twoje rynki" i harmonogram ingestii spinają się w jednym miejscu; dodanie rynku to wpis w tabeli, nie zmiana kodu
- (−) słownik trzeba ręcznie zasiać i utrzymywać (zmiana rzadka)
- (−) cykl FK `markets ⇄ assets` wymaga trzyetapowej migracji (skill `alembic-migracja`)

Startowa lista rynków: `docs/slownik-rynkow.md`.
