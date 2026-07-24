# ADR-003: Snapshoty dzienne wartości portfela

**Status:** Zaakceptowana (przeniesiona z v1, w wersji uproszczonej)
**Data:** 2026-07-20

## Decyzja

Wartość każdego portfela zapisywana raz dziennie po ingestii EOD do `portfolio_valuations (portfolio_id, date, value_pln, composition_change)`. W v2 **bez kolumny przepływów pieniężnych** — ta znika razem z ADR-006.

Wykres wartości i wszystkie metryki ryzyka liczone są z tej serii, nie z rekonstrukcji stanu.

## Konsekwencje

- (+) wykres i metryki są tanie w odczycie; brak przeliczania historii
- (−) historia zaczyna się w dniu rozpoczęcia monitoringu, nie w dniu zakupu aktywów (patrz ADR-101)
- (−) metryki wymagają minimum obserwacji — poniżej 30 dni nie prezentujemy zmienności i Sharpe'a
