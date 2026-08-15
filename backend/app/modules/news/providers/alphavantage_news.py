"""`AlphaVantageNewsProvider` — newsy **z oceną sentymentu** (plan krok 46,
etap 9), REST `https://www.alphavantage.co/query?function=NEWS_SENTIMENT`.

**Po co trzeci dostawca newsów.** RSS daje treść bez sentymentu, Finnhub daje
pewne powiązanie bez sentymentu (`/news-sentiment` zwraca na darmowym planie
`403 {"error":"You don't have access to this resource."}` — sprawdzone
2026-08-10 realnym kluczem). Bez Alpha Vantage parametr
`?with_sentiment_only=true` z `docs/api-kontrakt.md` byłby filtrem, który
zawsze zwraca pustą listę — obietnicą bez pokrycia (CLAUDE.md #3.15).

**Dlaczego zapisujemy `overall_sentiment_score`, a nie `ticker_sentiment`.**
Alpha Vantage podaje oba: ocenę całego artykułu i osobną ocenę per wymieniona
spółka. Kuszące jest to drugie (precyzyjniejsze), ale `news.sentiment` jest
kolumną **newsu**, nie pary news–aktywo: depesza o AAPL i MSFT trafiłaby do
bazy raz, a `INSERT ... ON CONFLICT DO NOTHING` zachowałby ocenę tego symbolu,
o który akurat zapytaliśmy pierwsi. Sentyment tej samej depeszy zależałby więc
od kolejności pętli — cichy niedeterminizm. `overall_sentiment_score` dotyczy
artykułu i jest ten sam niezależnie od pytania, więc jako jedyny pasuje do
dzisiejszego modelu danych. Ocena per spółka wymagałaby kolumny w
`news_assets` i jest świadomie poza zakresem tego kroku.

**Jedno zapytanie na wiele symboli.** `tickers` przyjmuje listę po przecinku,
a darmowy plan to **25 zapytań na dobę** — pętla „symbol po symbolu" przy
jobie co pół godziny przekroczyłaby dobowy budżet już na jednym symbolu
(48 przebiegów). Stąd `get_news_batch` obok wymaganego protokołem
`get_news`, oraz osobny, rzadszy harmonogram w `worker/scheduler.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.http_client import decimal_or_none, get_with_backoff
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news.providers.base import NewsCapability, NewsItem

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT = 15.0
# Maksimum, jakie oddaje darmowy plan w jednej odpowiedzi. Wyżej nie ma sensu
# prosić — a niżej znaczyłoby gubić newsy między przebiegami.
_LIMIT = 50

# Minimalna trafność, przy której uznajemy, że artykuł JEST o tej spółce,
# a nie tylko ją wymienia.
#
# `ticker_sentiment` Alpha Vantage wylicza wszystkie spółki wspomniane
# w tekście i każdej daje `relevance_score` z zakresu 0–1. Ocena jest jednak
# **zawyżona przez samo zapytanie**: przy `tickers=AAPL,MSFT` artykuł
# zatytułowany „Apple Downgraded as Soaring Memory Costs Test iPhone Pricing
# Power" dostaje MSFT z wynikiem 0,61. Próg względny („najwyższy wynik
# w artykule") też nie działa, bo w tekstach o całym rynku najwyższy wynik
# bywa przypadkowy.
#
# Zmierzone na żywym feedzie (50 artykułów, 2026-08-11): bez progu powstaje
# 100 powiązań, choć tylko 6 artykułów w ogóle wspomina Apple lub Microsoft
# w tytule. Próg 0,5 przepuszcza wszystkie 100, próg 0,7 — 24, próg 0,9 —
# dokładnie te 6 i ani jednego więcej. Stąd 0,9.
#
# To NIE jest strojenie precyzji dla estetyki feedu. Powiązania z Alpha
# Vantage zapisujemy jako `match_confidence='source'`, czyli UI pokaże je
# jako fakt, nie przybliżenie — a „wspomniano nazwę spółki" nie jest faktem
# „ten news dotyczy Twojej pozycji" (CLAUDE.md #3.15).
_MIN_RELEVANCE = Decimal("0.9")


class AlphaVantageNewsProvider:
    """`supports = {NewsCapability.PER_SYMBOL}` — bez symbolu nie ma czego
    zwrócić (kontrakt w `base.py`: wywołanie w nieobsługiwanym trybie zwraca
    pustą listę, nie rzuca wyjątkiem)."""

    name = "alphavantage_news"
    supports = {NewsCapability.PER_SYMBOL}

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        limiter: RateLimiter | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_alphavantage)
        # `None` = czytaj leniwie przy wywołaniu, tak samo jak
        # `FinnhubNewsProvider` — żeby testy mogły nadpisać `Settings`
        # bez rekonstrukcji providera.
        self._api_key = api_key

    async def get_news(self, *, symbol: str | None = None) -> list[NewsItem]:
        if symbol is None:
            return []
        return await self.get_news_batch([symbol])

    async def get_news_batch(self, symbols: list[str]) -> list[NewsItem]:
        """Newsy dla wielu symboli w **jednym** zapytaniu (patrz docstring
        modułu — dobowy budżet darmowego planu tego wymaga)."""
        if not symbols:
            return []

        api_key = (
            self._api_key if self._api_key is not None else get_settings().alphavantage_api_key
        )
        if not api_key:
            raise ProviderUnavailableError(
                "Brak ALPHAVANTAGE_API_KEY — dostawca sentymentu niedostępny.",
                details={"provider": self.name},
            )

        response = await get_with_backoff(
            self._client,
            _BASE_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(symbols),
                "limit": str(_LIMIT),
                "sort": "LATEST",
                "apikey": api_key,
            },
            limiter=self._limiter,
            request_timeout=_REQUEST_TIMEOUT,
        )
        payload = response.json()
        feed = self._feed_or_raise(payload, symbols)
        requested = {s.upper() for s in symbols}
        return [item for raw in feed if (item := self._parse_entry(raw, requested)) is not None]

    def _feed_or_raise(self, payload: Any, symbols: list[str]) -> list[Any]:
        """Wyciąga `feed` albo rzuca `ProviderUnavailableError`.

        Alpha Vantage **nie używa kodów HTTP do sygnalizowania błędów** —
        wyczerpany limit dobowy, zły klucz i nieznana funkcja wracają jako
        `200 OK` z kluczem `Information`/`Note`/`Error Message` zamiast
        `feed`. Bez tej kontroli `payload.get("feed", [])` zamieniłoby każdą
        z tych awarii w „dziś nic nie było o Twoich spółkach", a obwód
        (`CircuitBreaker`) nigdy by się nie otworzył.
        """
        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                "Alpha Vantage zwrócił odpowiedź w nieoczekiwanym kształcie.",
                details={"provider": self.name},
            )
        for key in ("Information", "Note", "Error Message"):
            message = payload.get(key)
            if message:
                raise ProviderUnavailableError(
                    f"Alpha Vantage odmówił odpowiedzi: {message}",
                    details={"provider": self.name, "tickers": ",".join(symbols)},
                )
        feed = payload.get("feed")
        if not isinstance(feed, list):
            raise ProviderUnavailableError(
                "Alpha Vantage nie zwrócił listy `feed`.",
                details={"provider": self.name, "tickers": ",".join(symbols)},
            )
        return feed

    def _parse_entry(self, raw: Any, requested: set[str]) -> NewsItem | None:
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        published = _parse_time(raw.get("time_published"))
        if not title or not url or published is None:
            return None

        symbols = tuple(
            ticker
            for ticker, relevance in _tickers(raw.get("ticker_sentiment"))
            if ticker in requested and relevance >= _MIN_RELEVANCE
        )
        if not symbols:
            return None

        sentiment = decimal_or_none(raw.get("overall_sentiment_score"))
        return NewsItem(
            title=title,
            url=url,
            # Realny wydawca (Benzinga, Zacks...), nie „alphavantage" —
            # tak samo jak przy RSS i Finnhubie, gdzie w feedzie użytkownika
            # ma się pokazać źródło depeszy, a nie nasz pośrednik.
            source=str(raw.get("source") or self.name).strip(),
            published_at=published,
            summary=str(raw.get("summary") or "").strip() or None,
            sentiment=sentiment,
            # Podpis stawiamy tylko wtedy, gdy ocena naprawdę przyszła —
            # `sentiment_source` bez `sentiment` sugerowałby, że ktoś ocenił
            # i wyszło zero (CLAUDE.md #3.15).
            sentiment_source=self.name if sentiment is not None else None,
            symbols=symbols,
        )


def _tickers(raw: Any) -> list[tuple[str, Decimal]]:
    """`ticker_sentiment` jako pary `(ticker, relevance_score)`.

    Wpis bez czytelnego `relevance_score` dostaje `0` — czyli wypada przez
    próg. Brak oceny trafności to nie jest powód, żeby uznać powiązanie
    za pewne.
    """
    if not isinstance(raw, list):
        return []
    pairs: list[tuple[str, Decimal]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("ticker"):
            continue
        relevance = decimal_or_none(entry.get("relevance_score")) or Decimal(0)
        pairs.append((str(entry["ticker"]).upper(), relevance))
    return pairs


def _parse_time(raw: Any) -> datetime | None:
    """`time_published` ma format `YYYYMMDDTHHMMSS` **bez strefy** — Alpha
    Vantage dokumentuje go jako czas amerykański rynkowy, ale nie podaje
    offsetu ani nie zmienia formatu przy zmianie czasu.

    Traktujemy go jako UTC i robimy to **jawnie**: naiwny `datetime`
    wpadłby do kolumny `timestamptz` z założeniem strefy serwera, czyli ta
    sama depesza miałaby inny czas na VPS-ie i na laptopie, a przez to inny
    `content_hash` i podwójny wpis w feedzie. Przesunięcie względem
    prawdziwej strefy publikacji jest stałe i nie zmienia kolejności w
    feedzie; niedeterminizm zmieniałby.
    """
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
