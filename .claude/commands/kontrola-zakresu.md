---
description: Sprawdź, czy projekt nie wypełzł poza założony zakres
---

Sprawdź pełzanie zakresu.

Przeszukaj kod pod kątem rzeczy świadomie wykluczonych z v2:
- transakcje / `transactions`, kupno-sprzedaż, FIFO, LIFO
- zrealizowany P/L, XIRR, TWR, przepływy pieniężne / `cash_flow`
- przeliczanie historii, `dirty_from`, mutowanie snapshotów wstecz
- import CSV od brokerów, rozliczenia podatkowe

Dla każdego trafienia oceń: czy to faktyczne wyjście poza zakres, czy tylko nazewnictwo. Sprawdź też, czy nie powstały funkcje spoza planu 50 kroków.

Osobno sprawdź kierunek odwrotny — czy nie zabetonowaliśmy „drogi powrotu" z sekcji 10 projektu: czy `holdings` da się w przyszłości zamienić na projekcję z transakcji, czy `valid_from` istnieje, czy kwoty są `NUMERIC(20,8)`.

Raport: co wypełzło, co odciąć, co zgłosić jako świadomą zmianę zakresu do mojej akceptacji.
