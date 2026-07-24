# ADR-101: Semantyka historii przy edycji pozycji

**Status:** Zatwierdzona (2026-07-24)
**Data:** 2026-07-20
**Dotyczy kroków:** 1, 17, 25, 27, 40

## Kontekst

Użytkownik zmienia ilość (dokupił lub sprzedał poza aplikacją) albo dodaje nową pozycję. Pytanie: co dzieje się z wykresem wartości portfela za poprzednie miesiące?

## Rozważane opcje

| Opcja | Złożoność | Zachowanie |
|---|---|---|
| A: Historia „od teraz" — snapshoty niemutowalne, edycja wpływa tylko na przyszłe dni | Niska | wykres pokazuje faktyczną historię monitoringu; skok wartości w dniu edycji jest naturalny |
| B: Pozycje z datą obowiązywania (`valid_from`), historia przeliczalna wstecz | Średnia | wierniejsza przeszłość, wraca problem przeliczania ogona i pytania „od kiedy to miałeś" |
| C: Retroaktywnie bieżący koszyk („gdybym zawsze trzymał to, co dziś") | Niska | użyteczne jako symulacja, fałszywe jako historia |

## Decyzja

**Opcja A** jako domyślna semantyka: snapshoty append-only. Dodatkowo pole `valid_from` w `holdings` już teraz (nullable, domyślnie data dodania), żeby opcja B była możliwa bez migracji łamiącej. Opcja C nigdy jako „historia portfela"; ewentualnie później jako jawnie nazwana symulacja.

## Konsekwencje

- (+) zero mechanizmu `dirty_from`, snapshoty trywialne, brak przeliczania ogona
- (−) dzień edycji pozycji = skok na wykresie; wymaga znacznika `composition_change` na osi czasu i wyłączenia tego dnia z serii zwrotów
- (do rewizji) opcja B, jeśli użytkownicy będą chcieli uzupełniać przeszłość

## Wpływ na implementację

- `portfolio_valuations` ma kolumnę `composition_change BOOLEAN`
- silnik zwrotów pomija dni ze znacznikiem (skill `analityka-struktury`)
- UI oznacza te dni pionową linią z tooltipem
