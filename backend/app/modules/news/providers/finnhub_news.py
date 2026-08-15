"""`FinnhubNewsProvider` — newsy spółkowe z Finnhub (plan krok 46, etap 9),
REST `https://finnhub.io/api/v1/company-news`.

**Osobny plik, nie metoda w `marketdata/providers/finnhub.py`.** Tamten
provider ma zaszyty `_BASE_URL` endpointu świec i implementuje `DataProvider`
(OHLCV/FX/metadane). News to inny protokół (`NewsProvider`) i inny endpoint;
dopisanie go tam wymagałoby przebudowy `_fetch` pod dwa adresy w module,
który dziś działa — czyli refaktoru cudzego obszaru przy okazji (CLAUDE.md
§4.3). Klucz API i limit zapytań są te same (`finnhub_api_key`,
`rate_limit_finnhub`), więc nic się nie dubluje poza kilkoma linijkami
pobrania.

**Co ten dostawca wnosi ponad RSS: pewność powiązania.** Feed RSS wymaga
zgadywania, o której spółce jest depesza (`matching.py`, heurystyka na
polskim tekście, z udokumentowanymi wpadkami). Finnhub odpowiada na pytanie
„newsy dla symbolu AAPL" — powiązanie podaje **źródło**, więc zapisujemy je
jako `MatchConfidence.SOURCE` i UI może je pokazać inaczej niż zgadywankę.

**Czego ten dostawca NIE wnosi: sentymentu.** `/company-news` go nie zawiera,
a osobny `/news-sentiment` zwraca na darmowym planie
`403 {"error":"You don't have access to this resource."}` (sprawdzone
2026-08-10 realnym kluczem). Świadomie **nie** wyliczamy sentymentu sami
z treści — byłaby to liczba wyglądająca na pomiar dostawcy, a będąca naszą
zgadywanką (CLAUDE.md #3.13, #3.15). Źródłem sentymentu pozostaje Alpha
Vantage (`NEWS_SENTIMENT`, darmowy plan go oddaje) — poza zakresem tego
pliku.

**Zakres: wyłącznie rynki zagraniczne.** Finnhub nie pokrywa GPW; pytanie
go o `CDR` czy `PKN` zwróci pustą listę i spali limit zapytań. Wybór aktywów
należy do warstwy ingestii (job czyta `asset_source_map`), nie tutaj.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.http_client import get_with_backoff
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news.providers.base import NewsCapability, NewsItem

logger = structlog.get_logger(__name__)

_BASE_URL = "https://finnhub.io/api/v1/company-news"
_REQUEST_TIMEOUT = 10.0


class FinnhubNewsProvider:
    """`supports = {NewsCapability.PER_SYMBOL}` — bez symbolu nie ma czego
    zwrócić (kontrakt w `base.py`: wywołanie w nieobsługiwanym trybie zwraca
    pustą listę, nie rzuca wyjątkiem)."""

    name = "finnhub_news"
    supports = {NewsCapability.PER_SYMBOL}

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        lookback_days: int = 7,
        limiter: RateLimiter | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client
        self._lookback_days = lookback_days
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_finnhub)
        # `None` = czytaj leniwie przy wywołaniu, tak samo jak
        # `FinnhubProvider` — żeby testy mogły nadpisać `Settings` bez
        # rekonstrukcji providera.
        self._api_key = api_key

    async def get_news(self, *, symbol: str | None = None) -> list[NewsItem]:
        if symbol is None:
            return []

        api_key = self._api_key if self._api_key is not None else get_settings().finnhub_api_key
        if not api_key:
            raise ProviderUnavailableError(
                "Brak FINNHUB_API_KEY — dostawca newsów Finnhub niedostępny.",
                details={"provider": self.name},
            )

        today = datetime.now(UTC).date()
        start = date.fromordinal(today.toordinal() - self._lookback_days)
        response = await get_with_backoff(
            self._client,
            _BASE_URL,
            params={
                "symbol": symbol,
                "from": start.isoformat(),
                "to": today.isoformat(),
                "token": api_key,
            },
            limiter=self._limiter,
            request_timeout=_REQUEST_TIMEOUT,
        )
        payload = response.json()
        if not isinstance(payload, list):
            # Finnhub przy błędzie autoryzacji oddaje obiekt `{"error": ...}`,
            # nie listę. Bez tej kontroli iterowalibyśmy po kluczach słownika
            # i dostali pustą listę newsów — czyli awarię wyglądającą jak
            # „dziś nic nie było".
            raise ProviderUnavailableError(
                "Finnhub zwrócił odpowiedź w nieoczekiwanym kształcie.",
                details={"provider": self.name, "symbol": symbol},
            )

        return [item for raw in payload if (item := self._parse_entry(raw, symbol)) is not None]

    def _parse_entry(self, raw: Any, symbol: str) -> NewsItem | None:
        if not isinstance(raw, dict):
            return None
        headline = str(raw.get("headline") or "").strip()
        url = str(raw.get("url") or "").strip()
        published_ts = raw.get("datetime")
        # `bool` jest podklasą `int`, więc bez jawnego wykluczenia `True`
        # przeszłoby jako znacznik czasu i dało 1970-01-01.
        if (
            not headline
            or not url
            or isinstance(published_ts, bool)
            or not isinstance(published_ts, (int, float))
        ):
            return None

        summary = str(raw.get("summary") or "").strip() or None
        # `source` to nazwa serwisu, który depeszę opublikował (Reuters,
        # CNBC...), nie „finnhub" — Finnhub jest tu pośrednikiem, a w feedzie
        # użytkownika ma się pokazać realny wydawca, tak samo jak przy RSS.
        source = str(raw.get("source") or self.name).strip()

        return NewsItem(
            title=headline,
            url=url,
            source=source,
            published_at=datetime.fromtimestamp(float(published_ts), tz=UTC),
            summary=summary,
            symbols=(symbol,),
        )
