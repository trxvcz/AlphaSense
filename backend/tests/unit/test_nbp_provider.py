"""Testy `NbpProvider` (`app.modules.marketdata.providers.nbp`).

Zero sieci — odpowiedzi NBP przechwycone przez `respx` (ten sam wzorzec co
`tests/integration/test_auth_oauth.py` dla Authlib/Google), treść wczytana
z nagranych fixture'ów w `tests/fixtures/providers/nbp/`.

**Pochodzenie fixture'ów:** `fx_eur_ok.json`, `fx_usd_ok.json`, `gold_ok.json`
i `not_found.txt` to odpowiedzi z **realnego** `api.nbp.pl` (środowisko
wykonujące ten krok miało dostęp do sieci z kontenera `api`) — zapytania:
`GET /api/exchangerates/rates/A/EUR/2026-07-20/2026-07-24/?format=json`,
`.../USD/...`, `GET /api/cenyzlota/2026-07-20/2026-07-24/?format=json`,
oraz (dla 404) zakres w całości weekendowy
`.../EUR/2026-07-18/2026-07-19/?format=json` i
`/api/cenyzlota/2026-07-18/2026-07-19/?format=json` — obie dały
`404 Not Found`, treść `not_found.txt`. Kształt payloadu (klucze
`table`/`currency`/`code`/`rates[].no/effectiveDate/mid` dla walut,
`data`/`cena` dla złota) jest więc zweryfikowany na żywo, nie tylko
z dokumentacji NBP.

Osobny test dymny na żywe `api.nbp.pl`, pod markerem `network`
(SKILL `data-provider`, sekcja „Testy") — wyłączony z CI (`ci.yml`:
`pytest -q -m "not network"`), uruchamiany tylko lokalnie.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from app.modules.marketdata.providers.base import Capability
from app.modules.marketdata.providers.nbp import GOLD_SYMBOL, NbpProvider

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "nbp"

_START = date(2026, 7, 20)
_END = date(2026, 7, 24)

_FX_EUR_URL = "http://api.nbp.pl/api/exchangerates/rates/A/EUR/2026-07-20/2026-07-24/?format=json"
_FX_USD_URL = "http://api.nbp.pl/api/exchangerates/rates/A/USD/2026-07-20/2026-07-24/?format=json"
_GOLD_URL = "http://api.nbp.pl/api/cenyzlota/2026-07-20/2026-07-24/?format=json"

_WEEKEND_START = date(2026, 7, 18)
_WEEKEND_END = date(2026, 7, 19)
_FX_WEEKEND_URL = (
    "http://api.nbp.pl/api/exchangerates/rates/A/EUR/2026-07-18/2026-07-19/?format=json"
)
_GOLD_WEEKEND_URL = "http://api.nbp.pl/api/cenyzlota/2026-07-18/2026-07-19/?format=json"


def _fixture_text(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text(encoding="utf-8")


def _fixture_json(name: str) -> object:
    return json.loads(_fixture_text(name))


def test_supports_only_fx_and_ohlcv() -> None:
    provider = NbpProvider()
    assert provider.supports == {Capability.FX, Capability.OHLCV}
    assert provider.name == "nbp"


async def test_get_fx_parses_normal_response() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_FX_EUR_URL).respond(json=_fixture_json("fx_eur_ok.json"))
        quotes = await provider.get_fx("EUR", _START, _END)

    assert [q.date for q in quotes] == [
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
    ]
    assert all(q.currency == "EUR" for q in quotes)
    assert quotes[0].rate_pln == Decimal("4.3359")
    assert quotes[-1].rate_pln == Decimal("4.3257")
    assert all(isinstance(q.rate_pln, Decimal) for q in quotes)


async def test_get_fx_lowercase_currency_is_normalised_to_uppercase() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_FX_USD_URL).respond(json=_fixture_json("fx_usd_ok.json"))
        quotes = await provider.get_fx("usd", _START, _END)

    assert all(q.currency == "USD" for q in quotes)
    assert quotes[0].rate_pln == Decimal("3.7906")


async def test_get_fx_returns_empty_list_on_404_whole_range_without_quotes() -> None:
    """Zakres w całości bez notowań (np. weekend) → 404 z NBP, nie błąd."""
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_FX_WEEKEND_URL).respond(status_code=404, text=_fixture_text("not_found.txt"))
        quotes = await provider.get_fx("EUR", _WEEKEND_START, _WEEKEND_END)

    assert quotes == []


async def test_get_fx_raises_on_unexpected_http_error() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_FX_EUR_URL).respond(status_code=500, text="internal error")
        with pytest.raises(httpx.HTTPStatusError):
            await provider.get_fx("EUR", _START, _END)


async def test_get_ohlcv_gold_maps_single_daily_price_to_ohlc_and_close_adj() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_GOLD_URL).respond(json=_fixture_json("gold_ok.json"))
        bars = await provider.get_ohlcv(GOLD_SYMBOL, _START, _END)

    assert len(bars) == 5
    first = bars[0]
    assert first.date == date(2026, 7, 20)
    assert first.open == first.high == first.low == first.close == first.close_adj
    assert first.close_adj == Decimal("487.21")
    assert first.volume is None
    assert bars[-1].close_adj == Decimal("499.29")


async def test_get_ohlcv_gold_returns_empty_list_on_404() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=True) as router:
        router.get(_GOLD_WEEKEND_URL).respond(status_code=404, text=_fixture_text("not_found.txt"))
        bars = await provider.get_ohlcv(GOLD_SYMBOL, _WEEKEND_START, _WEEKEND_END)

    assert bars == []


async def test_get_ohlcv_rejects_non_gold_symbol_without_network_call() -> None:
    provider = NbpProvider()
    with respx.mock(assert_all_called=False):
        with pytest.raises(ValueError, match="XAU"):
            await provider.get_ohlcv("CDR", _START, _END)


async def test_get_metadata_always_returns_none() -> None:
    provider = NbpProvider()
    assert await provider.get_metadata("EUR") is None
    assert await provider.get_metadata(GOLD_SYMBOL) is None


@pytest.mark.network
async def test_smoke_live_nbp_api_returns_recent_eur_rate() -> None:
    """Test dymny na żywe `api.nbp.pl` — wyłączony z CI (`-m "not network"`),
    uruchamiany ręcznie żeby wykryć zmianę kształtu odpowiedzi NBP.
    """
    provider = NbpProvider()
    try:
        quotes = await provider.get_fx("EUR", _START, _END)
    finally:
        await provider.aclose()

    assert len(quotes) >= 1
    assert all(quote.rate_pln > 0 for quote in quotes)
