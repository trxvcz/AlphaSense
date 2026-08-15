"""`RssProvider` — newsy z polskich feedów RSS (plan krok 46, etap 9).

Źródła domyślne: Bankier, Money, StockWatch (`Settings.news_rss_feeds`).

**Pobieranie idzie przez `httpx`, parsowanie przez `feedparser`.**
`feedparser.parse(url)` umie sam pobrać dokument, ale robi to synchronicznie
i własnym kodem sieciowym — w pętli zdarzeń workera zablokowałby wszystko
inne, a przy okazji ominąłby `RateLimiter`, `CircuitBreaker` i backoff na 429,
czyli całą warstwę odporności wymaganą przez CLAUDE.md #23. Dlatego pobieramy
sami i podajemy `feedparser` gotowy tekst.

**`feedparser` nie rzuca wyjątkami na zepsutym XML-u** — ustawia `bozo`
i zwraca tyle, ile zdołał sparsować. To dla nas zachowanie pożądane: jeden
uszkodzony wpis w feedzie nie ma kosztować całego przebiegu. Ale `bozo`
przy **zerowej** liczbie wpisów znaczy już co innego — dostaliśmy stronę
błędu albo HTML zamiast XML-a — i to traktujemy jako awarię dostawcy
(`ProviderUnavailableError`), tak samo jak `StooqProvider` traktuje
odpowiedź niebędącą CSV. Bez tego rozróżnienia padnięty feed wyglądałby
jak „dziś nie było newsów".

**Sentyment: zawsze `None`.** Żaden z polskich feedów go nie publikuje.
Świadomie **nie** zgadujemy go z tytułu ani nie liczymy słownikiem słów
nacechowanych — to byłaby liczba wyglądająca na pomiar, a będąca zgadywanką
(CLAUDE.md #3.13, #3.15). Ocena sentymentu pochodzi wyłącznie od dostawców,
którzy ją realnie liczą (Finnhub, Alpha Vantage) i jest wtedy podpisana
w `sentiment_source`.
"""

from __future__ import annotations

import re
from calendar import timegm
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.http_client import get_with_backoff
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news.providers.base import NewsCapability, NewsItem, is_safe_http_url

logger = structlog.get_logger(__name__)

_REQUEST_TIMEOUT = 15.0

# Wydawcy blokują żądania bez `User-Agent` — StockWatch oddaje na takie
# HTTP 403 (zaobserwowane przy pierwszym przebiegu joba). Przedstawiamy się
# nazwą aplikacji i adresem kontaktowym zamiast podszywać się pod
# przeglądarkę: to jest zwyczaj przy czytaniu publicznych feedów i daje
# wydawcy możliwość zablokowania nas celowo, jeśli sobie tego życzy.
_USER_AGENT = "AlphaSense/1.0 (+https://alphasense.cedron.net.pl; czytnik RSS portfela)"


def build_rss_client() -> httpx.AsyncClient:
    """Klient HTTP skonfigurowany pod feedy RSS.

    Dwie rzeczy, bez których feedy nie działają, a obie są własnością
    **klienta**, nie pojedynczego żądania — stąd fabryka, żeby job i testy
    nie musiały pamiętać o powtórzeniu tej konfiguracji:

    - `follow_redirects=True` — `httpx` domyślnie NIE podąża za
      przekierowaniami, a adresy feedów zmieniają się latami bez
      aktualizacji dokumentacji (money.pl oddaje 301 z `/rss/all.xml`
      na `/rss/rss.xml`). Bez tego stały, poprawny adres wygląda jak
      padnięty feed.
    - `User-Agent` — patrz `_USER_AGENT` wyżej.
    """
    return httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )


def _plain_text(html: str) -> str:
    """Skrót wpisu bez znaczników HTML.

    Feedy oddają `summary` jako **fragment HTML-a**, nie tekst — StockWatch
    dokłada `<p>`, linki i doklejkę „The post ... first appeared on ...".
    Front renderuje skrót jako tekst (React escapuje wartości), więc bez
    tego czyszczenia użytkownik zobaczyłby w feedzie dosłowne `<p>` i
    `<a href="...">`.

    Czyścimy **przy zapisie**, nie przy odczycie: `summary` trafia do bazy
    raz, a konsumentów będzie więcej niż jeden (feed, push w kroku 50).
    Świadomie zwykłe usunięcie znaczników, a nie parser HTML-a — nie
    renderujemy tej treści jako HTML nigdzie, więc nie ma tu problemu
    bezpieczeństwa do rozwiązania, jest problem czytelności.
    """
    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _source_from_url(url: str) -> str:
    """Nazwa źródła z domeny feedu (`www.bankier.pl/rss/...` → `bankier.pl`).

    Wolimy to od zaszytej mapy `URL → nazwa`: dodanie feedu w zmiennej
    środowiskowej nie ma wymagać zmiany w kodzie, a domena jest jedyną
    informacją o pochodzeniu, którą mamy **zawsze** — tytuł kanału bywa
    pusty albo identyczny dla kilku feedów tego samego wydawcy.
    """
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.") or url


def _published_at(entry: Any) -> datetime | None:
    """Moment publikacji wpisu jako UTC, albo `None`, gdy feed go nie podał.

    `feedparser` rozkłada datę na `published_parsed` (`time.struct_time`)
    już **przeliczoną do UTC** — o ile w ogóle zdołał ją odczytać. Dla wpisu
    bez daty albo z datą w formacie, którego nie rozpoznał, pole jest `None`
    i wtedy wpis pomijamy: bez momentu publikacji nie da się ani posortować
    feedu, ani odciąć archiwum przez `news_max_age_days`, ani policzyć
    `content_hash` (który datę zawiera).

    `timegm`, nie `mktime`: `mktime` interpretuje `struct_time` jako czas
    **lokalny** procesu, co na serwerze w innej strefie przesunęłoby każdą
    datę o kilka godzin — cichy błąd, bo wynik nadal wygląda poprawnie.
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        return None
    return datetime.fromtimestamp(timegm(parsed), tz=UTC)


class RssProvider:
    """`supports = {NewsCapability.FEED}` — RSS oddaje strumień wszystkiego,
    nie umie filtrować po symbolu. Wywołanie z `symbol` zwraca pustą listę
    (patrz kontrakt w `base.py`: brak wsparcia to nie awaria)."""

    name = "rss"
    supports = {NewsCapability.FEED}

    def __init__(
        self,
        client: httpx.AsyncClient,
        feeds: list[str] | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client
        self._feeds = feeds if feeds is not None else settings.rss_feed_list
        self._limiter = limiter or RateLimiter(self.name, settings.rate_limit_rss)

    async def get_news(self, *, symbol: str | None = None) -> list[NewsItem]:
        if symbol is not None:
            return []

        items: list[NewsItem] = []
        failures = 0
        for feed_url in self._feeds:
            try:
                items.extend(await self._fetch_feed(feed_url))
            except (httpx.HTTPError, ProviderUnavailableError) as exc:
                # Jeden padnięty feed nie ma przerywać pozostałych — ale jeśli
                # padły WSZYSTKIE, to jest awaria dostawcy i musi otworzyć
                # obwód, a nie udawać pustego dnia (patrz niżej).
                failures += 1
                logger.warning(
                    "rss_feed_failed",
                    provider=self.name,
                    feed=feed_url,
                    error=str(exc),
                )

        if self._feeds and failures == len(self._feeds):
            raise ProviderUnavailableError(
                "Żaden ze skonfigurowanych feedów RSS nie odpowiedział.",
                details={"provider": self.name, "feeds": len(self._feeds)},
            )
        return items

    async def _fetch_feed(self, feed_url: str) -> list[NewsItem]:
        response = await get_with_backoff(
            self._client,
            feed_url,
            params={},
            limiter=self._limiter,
            request_timeout=_REQUEST_TIMEOUT,
        )
        parsed = feedparser.parse(response.text)

        if not parsed.entries:
            # `bozo` + zero wpisów = dostaliśmy coś, co nie jest feedem
            # (strona błędu, wyzwanie anty-bot, HTML). Odróżnione od
            # poprawnego, ale pustego feedu — ten drugi jest w porządku.
            if parsed.bozo:
                raise ProviderUnavailableError(
                    "Odpowiedź nie jest poprawnym feedem RSS/Atom.",
                    details={
                        "provider": self.name,
                        "feed": feed_url,
                        "error": str(parsed.get("bozo_exception", "")),
                    },
                )
            return []

        source = _source_from_url(feed_url)
        items: list[NewsItem] = []
        skipped_no_date = 0
        for entry in parsed.entries:
            link = (getattr(entry, "link", "") or "").strip()
            title = (getattr(entry, "title", "") or "").strip()
            if not link or not title:
                continue
            if not is_safe_http_url(link):
                # Logowane osobno i głośniej niż brak daty: wpis bez daty to
                # niechlujstwo wydawcy, a `javascript:` w `<link>` to albo
                # przejęty feed, albo celowa próba — jedno i drugie chcemy
                # zobaczyć w logach, a nie policzyć po cichu.
                logger.warning(
                    "rss_entry_unsafe_url",
                    provider=self.name,
                    feed=feed_url,
                    url=link[:200],
                )
                continue
            published = _published_at(entry)
            if published is None:
                skipped_no_date += 1
                continue
            summary = _plain_text(getattr(entry, "summary", "") or "") or None
            items.append(
                NewsItem(
                    title=title,
                    url=link,
                    source=source,
                    published_at=published,
                    summary=summary,
                )
            )

        if skipped_no_date:
            logger.warning(
                "rss_entries_without_date",
                provider=self.name,
                feed=feed_url,
                skipped=skipped_no_date,
            )
        return items
