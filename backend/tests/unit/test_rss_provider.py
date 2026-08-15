"""Testy czyszczenia skrótu wpisu RSS (`RssProvider._plain_text`, krok 46).

Feedy oddają `summary` jako fragment HTML-a, nie tekst. Front renderuje ten
skrót jako tekst (React escapuje wartości), więc bez czyszczenia użytkownik
zobaczyłby w feedzie dosłowne `<p>` i `<a href="...">` — złapane dopiero na
żywym feedzie StockWatcha.

Przykłady poniżej są **przepisane z realnych odpowiedzi**, nie wymyślone.
"""

from __future__ import annotations

from app.modules.news.providers.rss import _plain_text


def test_usuwa_znaczniki_i_doklejke_wydawcy() -> None:
    raw = (
        "<p>Poniedziałek przyniósł kontynuację dobrej passy na GPW. WIG20 "
        "wyznaczył nowy rekord [&#8230;]</p>\n"
        '<p>The post <a href="https://www.stockwatch.pl/x">Nvidia i Intel</a> '
        'first appeared on <a href="https://www.stockwatch.pl/wiadomosci">StockWatch.pl</a>.</p>'
    )

    result = _plain_text(raw)

    assert "<p>" not in result
    assert "href" not in result
    assert result.startswith("Poniedziałek przyniósł kontynuację")
    # Encje HTML rozwinięte do znaków — `[&#8230;]` to wielokropek.
    assert "&#8230;" not in result
    assert "…" in result


def test_skleja_biale_znaki_z_lamania_wierszy() -> None:
    """Znacznik zamieniamy na spację, nie na pustkę — inaczej „a</p><p>b"
    skleiłoby się w „ab". Efektem ubocznym są podwójne spacje, które
    zwijamy."""
    assert _plain_text("<p>Zdanie\n  pierwsze.</p>\n<p>Drugie.</p>") == "Zdanie pierwsze. Drugie."


def test_czysty_tekst_przechodzi_bez_zmian() -> None:
    # Bankier oddaje skróty bez znaczników — czyszczenie nie ma ich psuć.
    assert _plain_text("WIG20 z nowym rekordem zamknięcia.") == "WIG20 z nowym rekordem zamknięcia."


def test_skrot_zlozony_wylacznie_ze_znacznikow_jest_pusty() -> None:
    """Pusty wynik wraca do `NewsItem` jako `None` (`or None` w wołającym) —
    czyli „brak skrótu", a nie skrót będący pustym stringiem."""
    assert _plain_text("<p></p>\n<br/>") == ""
