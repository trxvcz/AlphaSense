"""Test kontraktu produktowego dziedziny `?benchmark=` (krok 42).

**To nie jest test logiki** — to zapora przed cichą podmianą tego, co kryje
się pod kluczem, który widzi użytkownik. Decyzja 8 planu etapu 8: WIG20 nie
ma dziś darmowego źródła historii, więc liczy go ETF `ETFBW20TR`, a odpowiedź
musi to ujawniać (`approximate`, `note` — CLAUDE.md #3.15). Gdyby ktoś
przestawił `symbol` albo zgasił `approximate`, UI zacząłby przedstawiać
przybliżenie jako fakt i żaden test liczbowy by tego nie złapał.

Bez bazy i bez `client` — stąd `unit/`, nie `integration/`.
"""

from __future__ import annotations

from app.modules.analytics import service as analytics_service


def test_real_benchmark_mapping() -> None:
    """Na co wskazują klucze `?benchmark=` W PRODUKCJI."""
    wig20 = analytics_service.BENCHMARKS["WIG20"]

    assert wig20.symbol == "ETFBW20TR"
    assert wig20.approximate is True
    assert wig20.note and "ETF" in wig20.note

    sp500 = analytics_service.BENCHMARKS["^GSPC"]
    assert sp500.symbol == "^GSPC"
    assert sp500.approximate is False
