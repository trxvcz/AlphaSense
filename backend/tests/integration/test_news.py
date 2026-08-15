"""Testy `GET /portfolios/{id}/news` (plan krok 46, etap 9).

Integracyjne, prawdziwa baza — ten sam wzorzec co
`tests/integration/test_analytics.py`: aktywa testowe z losowym sufiksem
symbolu na rynkach obecnych w słowniku, sprzątanie po każdym teście.
Newsy wstawiamy **przez repozytorium**, nie przez joba: job pobiera z sieci
(feedy RSS, Finnhub, Alpha Vantage), a te testy sprawdzają odczyt i
autoryzację, nie ingestię. Logika dopasowania tekstu ma własne, czysto
jednostkowe pokrycie w `tests/unit/test_news_matching.py`.

Osią tych testów jest to, czego nie widać w kodzie feedu na pierwszy rzut
oka: news **nie należy do użytkownika**. Ta sama depesza jest powiązana
z aktywami wielu osób naraz, więc izolacja nie może polegać na filtrowaniu
po właścicielu wiersza — musi wynikać z tego, że feed powstaje wyłącznie
z aktywów portfela przekazanego przez `get_owned_portfolio`. Stąd nacisk na
`test_feed_nie_zdradza_symboli_z_cudzego_portfela`: ten sam wiersz `news`
ma dwóm użytkownikom pokazać dwie różne listy `assets`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.news import repository
from app.modules.news.matching import MatchConfidence
from app.modules.news.models import News, NewsAsset
from app.modules.portfolio.models import Holding
from app.modules.portfolio.service import today

EMAIL_A = "news-a@example.com"
EMAIL_B = "news-b@example.com"
PASSWORD = "correct-password-1"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_portfolio(client: AsyncClient, token: str, name: str = "Portfel") -> str:
    resp = await client.post(
        "/api/portfolios", json={"name": name, "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


async def _add_holding(
    client: AsyncClient, token: str, portfolio_id: str, asset_id: uuid.UUID, quantity: str = "1"
) -> None:
    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(asset_id), "quantity": quantity},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


@dataclass
class NewsAssets:
    covered: Asset  # ma powiązane newsy
    uncovered: Asset  # nie ma żadnego newsu — trafia do `assets_without_news`


@pytest_asyncio.fixture
async def news_assets(db_session: AsyncSession) -> AsyncGenerator[NewsAssets, None]:
    suffix = uuid.uuid4().hex[:8]
    covered = Asset(
        symbol=f"NWSA{suffix}",
        name=f"News Covered {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
        sector="Technologia",
        country="Polska",
    )
    uncovered = Asset(
        symbol=f"NWSB{suffix}",
        name=f"News Uncovered {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
        sector="Technologia",
        country="Polska",
    )
    db_session.add_all([covered, uncovered])
    await db_session.commit()
    await db_session.refresh(covered)
    await db_session.refresh(uncovered)

    d = today()
    db_session.add_all(
        [
            Price(asset_id=covered.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
            Price(asset_id=uncovered.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
        ]
    )
    await db_session.commit()

    yield NewsAssets(covered=covered, uncovered=uncovered)

    asset_ids = [covered.id, uncovered.id]
    # `news_assets` znika kaskadą po `assets`, ale same wiersze `news` już nie
    # (nie mają FK do aktywa) — kasujemy je po `url`, który każdy test
    # znakuje sufiksem swojego aktywa.
    await db_session.execute(delete(NewsAsset).where(NewsAsset.asset_id.in_(asset_ids)))
    await db_session.execute(delete(News).where(News.url.like(f"%{suffix}%")))
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    await db_session.execute(delete(FxRate).where(FxRate.currency == "XTS", FxRate.date == d))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


async def _insert_news(
    db: AsyncSession,
    *,
    asset_ids: list[uuid.UUID],
    slug: str,
    title: str = "Testowa depesza",
    minutes_ago: int = 5,
    sentiment: Decimal | None = None,
    sentiment_source: str | None = None,
    confidence: MatchConfidence = MatchConfidence.HEURISTIC,
) -> uuid.UUID:
    published_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    news_id = await repository.upsert_news(
        db,
        title=title,
        url=f"https://example.test/{slug}",
        source="example.test",
        published_at=published_at,
        fetched_at=datetime.now(UTC),
        content_hash=f"hash-{slug}",
        summary="Skrót depeszy.",
        sentiment=sentiment,
        sentiment_source=sentiment_source,
    )
    assert news_id is not None
    await repository.link_news_to_assets(
        db,
        news_id=news_id,
        asset_ids=asset_ids,
        published_at=published_at,
        match_confidence=confidence,
    )
    await db.commit()
    return news_id


async def test_feed_zwraca_newsy_aktywow_z_portfela(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    await _add_holding(client, token, portfolio_id, news_assets.uncovered.id)
    slug = news_assets.covered.symbol
    await _insert_news(db_session, asset_ids=[news_assets.covered.id], slug=slug)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    urls = [item["url"] for item in body["items"]]
    assert f"https://example.test/{slug}" in urls
    # Aktywo bez newsów ma być NAZWANE, a nie po cichu pominięte: pusty feed
    # i feed niepełny wyglądają dla użytkownika tak samo (CLAUDE.md #3.15).
    assert news_assets.uncovered.symbol in body["assets_without_news"]
    assert news_assets.covered.symbol not in body["assets_without_news"]


async def test_feed_rozroznia_pewnosc_powiazania(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """`source` (dostawca podał powiązanie) kontra `heuristic` (nasze
    dopasowanie tekstu) musi dojechać do UI — inaczej przybliżenie wygląda
    jak fakt (CLAUDE.md #3.15)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    base = news_assets.covered.symbol
    await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=f"{base}-src",
        confidence=MatchConfidence.SOURCE,
    )
    await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=f"{base}-heu",
        minutes_ago=10,
        confidence=MatchConfidence.HEURISTIC,
    )

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    by_url = {item["url"]: item for item in resp.json()["items"]}
    src = by_url[f"https://example.test/{base}-src"]
    heu = by_url[f"https://example.test/{base}-heu"]
    assert src["assets"] == [{"symbol": base, "match_confidence": "source"}]
    assert heu["assets"] == [{"symbol": base, "match_confidence": "heuristic"}]


async def test_feed_z_filtrem_sentymentu_pomija_newsy_bez_oceny(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    base = news_assets.covered.symbol
    await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=f"{base}-sent",
        sentiment=Decimal("0.12345678"),
        sentiment_source="alphavantage_news",
    )
    await _insert_news(
        db_session, asset_ids=[news_assets.covered.id], slug=f"{base}-nosent", minutes_ago=10
    )

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/news",
        params={"with_sentiment_only": "true"},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["url"] for i in items] == [f"https://example.test/{base}-sent"]
    # Liczba dziesiętna wychodzi z API STRINGIEM, nigdy `float` (CLAUDE.md #3.1).
    assert items[0]["sentiment"] == "0.12345678"
    assert items[0]["sentiment_source"] == "alphavantage_news"


async def test_feed_oznacza_brak_oceny_sentymentu_jako_null(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """`sentiment=null` + `sentiment_source=null` to „nikt nie oceniał",
    co jest czymś innym niż „oceniono neutralnie" (`0` z podpisem)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    slug = f"{news_assets.covered.symbol}-plain"
    await _insert_news(db_session, asset_ids=[news_assets.covered.id], slug=slug)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    item = next(i for i in resp.json()["items"] if i["url"].endswith(slug))
    assert item["sentiment"] is None
    assert item["sentiment_source"] is None


async def test_filtr_sentymentu_zaweza_przed_limitem(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """Ocenione newsy leżące GŁĘBIEJ niż `limit` mają się w filtrze znaleźć.

    Regresja na realny błąd: filtr działał na liście już przyciętej przez
    `LIMIT`, więc portfel z przewagą GPW (same newsy bez sentymentu wśród
    najnowszych) dostawał pustkę, choć ocenione newsy o spółkach
    zagranicznych leżały w bazie dzień głębiej. UI mówił wtedy „żaden news
    nie ma oceny wydźwięku" — zdanie fałszywe (CLAUDE.md #3.15).

    Układ: pięć świeżych newsów bez oceny, dwa starsze z oceną, `limit=3`.
    Filtrowanie po przycięciu zwróciłoby tu **zero** pozycji.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    base = news_assets.covered.symbol

    for i in range(5):
        await _insert_news(
            db_session,
            asset_ids=[news_assets.covered.id],
            slug=f"{base}-swiezy-{i}",
            minutes_ago=i,
        )
    for i in range(2):
        await _insert_news(
            db_session,
            asset_ids=[news_assets.covered.id],
            slug=f"{base}-oceniony-{i}",
            minutes_ago=100 + i,
            sentiment=Decimal("0.20000000"),
            sentiment_source="alphavantage_news",
        )

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/news",
        params={"limit": "3", "with_sentiment_only": "true"},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(i["sentiment"] == "0.20000000" for i in items)


async def test_powiazanie_od_zrodla_podnosi_pewnosc_heurystyczna(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """`heuristic → source`, gdy ta sama depesza przyjdzie drugą drogą.

    Realny przebieg: RSS tagował depeszę zgadywanką, potem Finnhub (albo
    Alpha Vantage) podał to samo powiązanie jako pewne. Bez podniesienia
    pewności fakt zostałby oznaczony jako przybliżenie tylko dlatego, że
    RSS był pierwszy.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    slug = f"{news_assets.covered.symbol}-upgrade"
    news_id = await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=slug,
        confidence=MatchConfidence.HEURISTIC,
    )

    await repository.link_news_to_assets(
        db_session,
        news_id=news_id,
        asset_ids=[news_assets.covered.id],
        published_at=datetime.now(UTC),
        match_confidence=MatchConfidence.SOURCE,
    )
    await db_session.commit()

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    item = next(i for i in resp.json()["items"] if i["url"].endswith(slug))
    assert item["assets"] == [{"symbol": news_assets.covered.symbol, "match_confidence": "source"}]


async def test_ocena_dojezdza_do_newsa_zapisanego_wczesniej_bez_oceny(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """Sentyment z Alpha Vantage ma dojechać do depeszy, którą wcześniej
    zapisał RSS albo Finnhub — obaj bez oceny.

    Realny przebieg i realny błąd: `upsert_news` robi `ON CONFLICT DO
    NOTHING`, więc drugie wejście tej samej depeszy nie wnosiło NICZEGO poza
    `match_confidence`, a `sentiment` szedł do kosza. Skutek był widoczny
    dokładnie tam, gdzie boli: `?with_sentiment_only=true` pokazywał pustkę,
    a UI twierdziło „nikt tego nie ocenił" — czyli przekłamanie z gatunku
    tych, przed którymi broni CLAUDE.md #3.15, tylko odwrócone.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    slug = f"{news_assets.covered.symbol}-sentyment"
    news_id = await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=slug,
        sentiment=None,
        sentiment_source=None,
    )

    filled = await repository.fill_missing_sentiment(
        db_session,
        news_id=news_id,
        sentiment=Decimal("0.34"),
        sentiment_source="alphavantage_news",
    )
    await db_session.commit()

    assert filled is True
    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/news?with_sentiment_only=true",
        headers=_auth(token),
    )

    item = next(i for i in resp.json()["items"] if i["url"].endswith(slug))
    # String w JSON, nie float (CLAUDE.md #3.1); skala z `NUMERIC(20,8)`.
    assert item["sentiment"] == "0.34000000"
    assert item["sentiment_source"] == "alphavantage_news"


async def test_ocena_juz_zapisana_nie_jest_nadpisywana(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """`WHERE sentiment IS NULL` jest kontraktem, nie optymalizacją.

    Bez tego warunku wartość w bazie zależałaby od kolejności przebiegów
    jobów, a nie od danych — a przy dwóch replikach workera kolejność nie
    jest niczym gwarantowana.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    slug = f"{news_assets.covered.symbol}-ocena-pierwsza"
    news_id = await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=slug,
        sentiment=Decimal("0.80"),
        sentiment_source="finnhub_news",
    )

    filled = await repository.fill_missing_sentiment(
        db_session,
        news_id=news_id,
        sentiment=Decimal("-0.90"),
        sentiment_source="alphavantage_news",
    )
    await db_session.commit()

    assert filled is False
    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    item = next(i for i in resp.json()["items"] if i["url"].endswith(slug))
    assert item["sentiment"] == "0.80000000"
    assert item["sentiment_source"] == "finnhub_news"


async def test_dopasowanie_heurystyczne_nie_obniza_pewnosci_od_zrodla(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """Kierunek odwrotny do poprzedniego testu **nie może** zadziałać.

    To jest niezmiennik klauzuli `where` w `link_news_to_assets`: jej
    usunięcie przechodziło całą suitę, a w produkcji przy najbliższym
    przebiegu RSS przeetykietowałoby każde powiązanie od dostawcy jako
    zgadywankę — czyli zamieniłoby fakt w przybliżenie (CLAUDE.md #3.15).
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, news_assets.covered.id)
    slug = f"{news_assets.covered.symbol}-nodowngrade"
    news_id = await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id],
        slug=slug,
        confidence=MatchConfidence.SOURCE,
    )

    await repository.link_news_to_assets(
        db_session,
        news_id=news_id,
        asset_ids=[news_assets.covered.id],
        published_at=datetime.now(UTC),
        match_confidence=MatchConfidence.HEURISTIC,
    )
    await db_session.commit()

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    item = next(i for i in resp.json()["items"] if i["url"].endswith(slug))
    assert item["assets"] == [{"symbol": news_assets.covered.symbol, "match_confidence": "source"}]


async def test_feed_obcego_portfela_zwraca_404(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """404, nie 403 — istnienie cudzego portfela też jest informacją
    (skill `izolacja-danych`)."""
    token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a)
    await _add_holding(client, token_a, portfolio_a, news_assets.covered.id)
    await _insert_news(
        db_session, asset_ids=[news_assets.covered.id], slug=news_assets.covered.symbol
    )

    token_b = await _register_and_login(client, EMAIL_B)
    resp = await client.get(f"/api/portfolios/{portfolio_a}/news", headers=_auth(token_b))

    assert resp.status_code == 404, resp.text


async def test_feed_nie_zdradza_symboli_z_cudzego_portfela(
    client: AsyncClient, db_session: AsyncSession, news_assets: NewsAssets
) -> None:
    """Ta sama depesza, dwóch użytkowników, dwie różne listy `assets`.

    Newsy są współdzielone (jeden wiersz `news` na całą bazę), więc lista
    powiązanych aktywów jest jedynym miejscem, w którym feed mógłby wynieść
    informację o cudzym portfelu. `B` trzyma `uncovered`, `A` trzyma
    `covered` — obaj widzą ten sam news, ale każdy wyłącznie swój symbol.
    """
    slug = f"{news_assets.covered.symbol}-shared"
    await _insert_news(
        db_session,
        asset_ids=[news_assets.covered.id, news_assets.uncovered.id],
        slug=slug,
    )

    token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a)
    await _add_holding(client, token_a, portfolio_a, news_assets.covered.id)

    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_b = await _create_portfolio(client, token_b)
    await _add_holding(client, token_b, portfolio_b, news_assets.uncovered.id)

    resp_a = await client.get(f"/api/portfolios/{portfolio_a}/news", headers=_auth(token_a))
    resp_b = await client.get(f"/api/portfolios/{portfolio_b}/news", headers=_auth(token_b))

    item_a = next(i for i in resp_a.json()["items"] if i["url"].endswith(slug))
    item_b = next(i for i in resp_b.json()["items"] if i["url"].endswith(slug))
    assert [a["symbol"] for a in item_a["assets"]] == [news_assets.covered.symbol]
    assert [a["symbol"] for a in item_b["assets"]] == [news_assets.uncovered.symbol]


async def test_feed_bez_pozycji_jest_pusty(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/news", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["assets_covered"] == 0
    assert body["assets_without_news"] == []


async def test_limit_poza_zakresem_zwraca_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/news", params={"limit": "500"}, headers=_auth(token)
    )

    assert resp.status_code == 422, resp.text
