"""Testy `AlphaVantageNewsProvider` (plan krok 46, etap 9).

Zero sieci — `respx` przechwytuje HTTP, payloady budowane w miejscu wg
kształtu odpowiedzi `NEWS_SENTIMENT` (ten sam wzorzec co
`tests/unit/test_finnhub_provider.py`, tylko bez pliku fixture: interesują
nas pojedyncze pola, nie cała nagrana odpowiedź na 50 pozycji).

Sedno tych testów jest jedno: **kiedy wolno powiedzieć „ten news dotyczy
tej spółki"**. Alpha Vantage wymienia w `ticker_sentiment` każdą wspomnianą
spółkę i przy zapytaniu o konkretne tickery zawyża im trafność (zmierzone
na żywym feedzie: artykuł „Apple Downgraded..." dostaje MSFT z wynikiem
0,61). Powiązania z tego dostawcy zapisujemy jako `match_confidence='source'`,
czyli UI pokaże je jako fakt — więc próg trafności nie jest kosmetyką feedu,
tylko warunkiem prawdziwości etykiety (CLAUDE.md #3.15).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news.providers.alphavantage_news import AlphaVantageNewsProvider

_URL = "https://www.alphavantage.co/query"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-av-news-*"):
        await get_redis().delete(key)


def _provider(
    client: httpx.AsyncClient, *, api_key: str | None = "test-key"
) -> AlphaVantageNewsProvider:
    limiter = RateLimiter(f"test-av-news-{uuid.uuid4().hex}", 60, redis=get_redis())
    return AlphaVantageNewsProvider(client, limiter=limiter, api_key=api_key)


def _article(
    *,
    title: str = "Apple Downgraded as Memory Costs Bite",
    url: str = "https://example.test/aapl",
    time_published: str = "20260811T143000",
    tickers: list[tuple[str, str]] | None = None,
    overall: Any = "0.15",
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "time_published": time_published,
        "summary": "Skrót.",
        "source": "Yahoo Finance",
        "overall_sentiment_score": overall,
        "ticker_sentiment": [
            {"ticker": t, "relevance_score": r, "ticker_sentiment_score": "0.1"}
            for t, r in (tickers if tickers is not None else [("AAPL", "1.000000")])
        ],
    }


async def _fetch(payload: Any, symbols: list[str] | None = None) -> list[Any]:
    async with httpx.AsyncClient() as client:
        provider = _provider(client)
        with respx.mock(assert_all_called=True) as router:
            router.get(_URL).respond(json=payload)
            return await provider.get_news_batch(symbols or ["AAPL", "MSFT"])


async def test_parsuje_wpis_z_sentymentem_i_realnym_wydawca() -> None:
    items = await _fetch({"feed": [_article()]})

    assert len(items) == 1
    item = items[0]
    assert item.title == "Apple Downgraded as Memory Costs Bite"
    assert item.sentiment == Decimal("0.15")
    assert item.sentiment_source == "alphavantage_news"
    # W feedzie użytkownika ma się pokazać wydawca depeszy, nie nasz pośrednik.
    assert item.source == "Yahoo Finance"
    assert item.symbols == ("AAPL",)


async def test_odrzuca_ticker_ponizej_progu_trafnosci() -> None:
    """MSFT wspomniany w tekście o Apple nie jest newsem „o MSFT".

    Wartość 0,61 nie jest wymyślona — tyle Alpha Vantage realnie przypisała
    Microsoftowi w artykule o obniżce rekomendacji Apple (2026-08-11).
    """
    items = await _fetch({"feed": [_article(tickers=[("AAPL", "1.000000"), ("MSFT", "0.608826")])]})

    assert items[0].symbols == ("AAPL",)


async def test_artykul_bez_zadnego_trafnego_tickera_wypada_calkowicie() -> None:
    """Artykuł, który tylko wymienia spółki, nie trafia do bazy w ogóle —
    zapisany, wypełniłby feed treścią nie na temat."""
    items = await _fetch({"feed": [_article(tickers=[("AAPL", "0.612363"), ("MSFT", "0.640336")])]})

    assert items == []


async def test_pomija_tickery_spoza_zapytania() -> None:
    """`ticker_sentiment` wymienia spółki, których nie ma w naszej bazie —
    wiązać wolno wyłącznie znane `asset_id`."""
    items = await _fetch(
        {"feed": [_article(tickers=[("AAPL", "1.000000"), ("NVDA", "1.000000")])]},
        symbols=["AAPL"],
    )

    assert items[0].symbols == ("AAPL",)


async def test_brak_oceny_nie_dostaje_podpisu_zrodla() -> None:
    """`sentiment_source` bez `sentiment` sugerowałby, że ktoś ocenił
    i wyszło zero (CLAUDE.md #3.15)."""
    items = await _fetch({"feed": [_article(overall=None)]})

    assert items[0].sentiment is None
    assert items[0].sentiment_source is None


async def test_czas_publikacji_jest_swiadomy_strefy() -> None:
    """Naiwny `datetime` wpadłby do `timestamptz` ze strefą serwera — ta
    sama depesza miałaby inny `content_hash` na VPS-ie i na laptopie."""
    items = await _fetch({"feed": [_article(time_published="20260811T143000")]})

    assert items[0].published_at == datetime(2026, 8, 11, 14, 30, tzinfo=UTC)


async def test_wpis_z_niepoprawna_data_jest_pomijany_bez_wywalania_reszty() -> None:
    payload = {
        "feed": [
            _article(time_published="wczoraj", url="https://example.test/zly"),
            _article(url="https://example.test/dobry"),
        ]
    }

    items = await _fetch(payload)

    assert [i.url for i in items] == ["https://example.test/dobry"]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"Information": "rate limit reached"}, id="limit-dobowy"),
        pytest.param({"Note": "Thank you for using Alpha Vantage"}, id="throttling"),
        pytest.param({"Error Message": "invalid API call"}, id="zly-parametr"),
        pytest.param({"nic": "tu nie ma"}, id="brak-klucza-feed"),
        pytest.param([1, 2, 3], id="nie-obiekt"),
    ],
)
async def test_awaria_zwrocona_jako_200_jest_bledem_dostawcy(payload: Any) -> None:
    """Alpha Vantage sygnalizuje awarie kodem 200 i kluczem `Information`/
    `Note`/`Error Message`. Bez tej kontroli wyczerpany limit dobowy
    wyglądałby jak „dziś nic nie było", a bezpiecznik nigdy by się nie
    otworzył."""
    with pytest.raises(ProviderUnavailableError):
        await _fetch(payload)


async def test_brak_klucza_api_to_awaria_dostawcy_nie_pusty_feed() -> None:
    async with httpx.AsyncClient() as client:
        provider = _provider(client, api_key="")
        with pytest.raises(ProviderUnavailableError):
            await provider.get_news_batch(["AAPL"])


async def test_get_news_bez_symbolu_zwraca_pusta_liste() -> None:
    """Kontrakt `NewsProvider` z `base.py`: wywołanie w nieobsługiwanym
    trybie nie jest awarią i nie ma otwierać obwodu."""
    async with httpx.AsyncClient() as client:
        assert await _provider(client).get_news() == []


async def test_pusta_lista_symboli_nie_wysyla_zapytania() -> None:
    """Zapytanie bez tickerów spaliłoby jedno z 25 dobowych zapytań
    darmowego planu, nie zwracając niczego użytecznego."""
    async with httpx.AsyncClient() as client:
        provider = _provider(client)
        with respx.mock(assert_all_called=False) as router:
            route = router.get(_URL).respond(json={"feed": []})
            assert await provider.get_news_batch([]) == []
            assert not route.called
