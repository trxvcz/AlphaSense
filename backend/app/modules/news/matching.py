"""Dopasowanie newsów do aktywów i deduplikacja (plan krok 46, etap 9).

Czyste funkcje, bez bazy i bez sieci — dzięki temu testy jednostkowe
liczą na znanych przykładach, a nie na mockach `AsyncSession`
(CLAUDE.md §8, „bez mocków bazy tam, gdzie obliczenie jest czysto
matematyczne"; tu zamiast liczby jest tekst, ale zasada ta sama).

**Czym to dopasowanie NIE jest.** Feedy RSS Bankiera czy Money nie niosą
tickerów — niosą polski tekst. Wiązanie newsu z aktywem jest więc
**heurystyką na tekście**, nie danymi od źródła, i tak trzeba je traktować
w UI (CLAUDE.md #3.15). Newsy od dostawcy per-symbol (Finnhub
`/company-news`) są w innej sytuacji: tam powiązanie podaje źródło i jest
pewne. Stąd `MatchConfidence` — bez tego rozróżnienia feed pokazywałby
zgadywankę obok faktu i nie dałoby się ich odróżnić.

**Dlaczego nie dopasowujemy po samym tickerze.** `PKN` w tytule owszem,
występuje, ale trzyliterowe kody giełdowe są w polskim tekście groźnie
niejednoznaczne, a dla części spółek ticker w prasie w ogóle nie pada
(pisze się „Orlen", nie „PKN"). Dopasowujemy więc po **nazwie aktywa**
i dodatkowo po tickerze, ale ticker wyłącznie jako **osobny wyraz pisany
wielkimi literami** — inaczej „CDR" łapałoby się w środku przypadkowych
słów, a `ETF` w nazwie funduszu tagowałby każdy fundusz.

**Znane ograniczenie: odmiana.** Dopasowanie idzie po całych wyrazach, więc
„Orlen" złapie się, a „Orlenu" i „Orlenem" już nie — a polski nagłówek
odmienia nazwy stale. Świadomie zostawione: stemming polski to nowa
zależność (CLAUDE.md §10) i osobna klasa błędów (fałszywe dopasowania po
skróconym rdzeniu), a dopasowanie po mianowniku daje wynik **zaniżony,
nie zmyślony** — news bez tagu po prostu nie pojawi się w feedzie
użytkownika, zamiast pojawić się przy złej spółce. To właściwa strona,
po której się mylić. Do rewizji, gdy zobaczymy, ile realnie umyka.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

# Słowa, które w nazwie aktywa nie niosą tożsamości spółki i samodzielnie
# nie mogą stanowić dopasowania. Bez tej listy „Grupa" albo „SA" w nazwie
# tagowałyby połowę feedu gospodarczego.
_STOPWORDS = frozenset(
    {
        "sa",
        "s",
        "a",
        "spolka",
        "spolki",
        "grupa",
        "group",
        "holding",
        "akcyjna",
        "etf",
        "fundusz",
        "inc",
        "corp",
        "corporation",
        "company",
        "co",
        "plc",
        "ag",
        "nv",
        "ltd",
        "the",
    }
)

# Nazwa krótsza niż to nie jest wiarygodnym dopasowaniem tekstowym.
_MIN_NAME_TOKEN_LENGTH = 3


class MatchConfidence(StrEnum):
    """Skąd wzięło się powiązanie newsu z aktywem.

    `SOURCE` — podał je dostawca (Finnhub `/company-news` pytany o symbol).
    `HEURISTIC` — wynik dopasowania tekstu po naszej stronie.

    UI ma obowiązek pokazać różnicę: pierwsze jest faktem, drugie
    przybliżeniem (CLAUDE.md #3.15).
    """

    SOURCE = "source"
    HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class AssetMatcher:
    """Aktywo sprowadzone do tego, po czym da się je rozpoznać w tekście.

    Budowane raz na przebieg joba dla wszystkich aktywów, potem stosowane
    do każdego newsu — stąd osobny typ zamiast przekazywania modeli ORM
    do funkcji dopasowującej (która dzięki temu nie zależy od SQLAlchemy
    i daje się testować na zwykłych krotkach).
    """

    asset_id: UUID
    symbol: str
    name_tokens: tuple[str, ...]


# Litery, których `unicodedata.normalize("NFKD", ...)` NIE rozkłada, bo nie
# są literą bazową z dołączonym znakiem diakrytycznym, tylko osobnym znakiem
# alfabetu. Dla polskiego to „ł" — i pominięcie go nie jest kosmetyką:
# „Złoto" rozpadało się wtedy na „z" + „oto", bo `_tokenize` traktuje każdy
# nierozpoznany znak jak separator. Token „oto" jest pospolitym polskim
# słowem, więc aktywo XAU tagowało się do połowy feedu („**Oto** gdzie
# szukać..."). Znalezione na żywych danych, nie w testach.
_NON_DECOMPOSABLE = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "ø": "o", "ß": "ss"})


def _strip_accents(text: str) -> str:
    """„Orlen Płock" → „orlen plock".

    Polskie znaki diakrytyczne bywają w feedach zapisane niekonsekwentnie
    (encje HTML, transliteracja w skrótach), a nazwa aktywa w bazie ma
    jeden ustalony zapis. Porównywanie bez ogonków usuwa całą tę klasę
    rozjazdów kosztem teoretycznej kolizji, której w praktyce nie ma.

    Kolejność jest istotna: najpierw podmiana liter nierozkładalnych
    (`_NON_DECOMPOSABLE`), dopiero potem NFKD — inaczej „ł" dotrwałoby do
    `_tokenize` i rozcięło wyraz na dwa bezużyteczne kawałki.
    """
    translated = text.lower().translate(_NON_DECOMPOSABLE)
    normalized = unicodedata.normalize("NFKD", translated)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z]+", _strip_accents(text)) if t]


def build_matcher(asset_id: UUID, symbol: str, name: str) -> AssetMatcher:
    """Buduje `AssetMatcher` z pól aktywa.

    Z nazwy zostają wyłącznie tokeny dłuższe niż `_MIN_NAME_TOKEN_LENGTH`
    i spoza `_STOPWORDS` — „CD Projekt SA" daje `("projekt",)`, bo „CD"
    jest za krótkie, a „SA" nic nie znaczy. Aktywo, z którego nie zostaje
    żaden token, będzie rozpoznawalne wyłącznie po tickerze i to jest
    zachowanie właściwe: nazwa złożona z samych słów pospolitych nie
    nadaje się do dopasowania tekstowego.

    **Tokeny czysto liczbowe odpadają.** „NASDAQ 100" i „FTSE 100" dawały
    token `100`, który pasował do każdego artykułu wspominającego liczbę
    sto — indeksy tagowały się wtedy do wiadomości o oprocentowaniu konta
    czy o tabletce na odchudzanie. Liczba nigdy nie identyfikuje spółki;
    nazwy indeksów zostają rozpoznawalne po członie słownym („nasdaq",
    „ftse") i po tickerze. Znalezione na żywych danych.
    """
    tokens = tuple(
        t
        for t in _tokenize(name)
        if len(t) >= _MIN_NAME_TOKEN_LENGTH and t not in _STOPWORDS and not t.isdigit()
    )
    return AssetMatcher(asset_id=asset_id, symbol=symbol, name_tokens=tokens)


def match_assets(title: str, summary: str | None, matchers: list[AssetMatcher]) -> list[UUID]:
    """Zwraca identyfikatory aktywów wspomnianych w tekście newsu.

    Dopasowanie jest spełnione, gdy w tekście występuje **ticker jako
    osobny wyraz wielkimi literami** albo **którykolwiek token nazwy**
    jako osobny wyraz. Sprawdzamy tytuł i skrót łącznie: sam tytuł bywa
    zbyt lakoniczny („Spółka podnosi prognozy"), a skrót zwykle zawiera
    nazwę.

    Ticker porównujemy na tekście **oryginalnym**, nie znormalizowanym —
    wielkość liter jest tu jedynym, co odróżnia ticker `PKN` od
    przypadkowego wyrazu. Nazwy porównujemy na tekście znormalizowanym,
    bo tam wielkość liter i ogonki tylko przeszkadzają.

    **Wiodący `^` odcinamy przed porównaniem.** Symbole indeksów mają go
    w bazie (`^NDX`, `^GDAXI`, `^FTSE` — konwencja yfinance), ale w tekście
    depeszy nikt tak nie pisze: dziennikarz napisze „Nasdaq" albo „NDX".
    Co gorsza `\\b` przed `^` w ogóle nie jest granicą słowa (oba znaki są
    niesłowne), więc nawet dosłowne „^NDX" w tekście wracało z `findall`
    jako `NDX` i porównanie z `^NDX` dawało `False`. Efekt: indeksy
    zagraniczne nie miały działającego dopasowania po tickerze **w żadnym
    przypadku** — rozpoznawały się wyłącznie po członie nazwy.
    """
    raw = f"{title} {summary or ''}"
    upper_words = set(re.findall(r"\b[A-Z0-9.]{2,}\b", raw))
    capitalized = _capitalized_tokens(raw)

    matched: list[UUID] = []
    for matcher in matchers:
        if matcher.symbol.upper().lstrip("^") in upper_words:
            matched.append(matcher.asset_id)
            continue
        if any(token in capitalized for token in matcher.name_tokens):
            matched.append(matcher.asset_id)
    return matched


def _capitalized_tokens(text: str) -> set[str]:
    """Tokeny, które w oryginalnym tekście zaczynają się wielką literą.

    **Po co ten warunek.** Nazwy spółek bywają pospolitymi rzeczownikami:
    „CD Projekt" daje token `projekt`, a „projekt" to zwyczajne polskie
    słowo. Bez rozróżnienia CDR tagowało się do zdania o refundacji pomp
    insulinowych, w którym padło słowo „projekt" — znalezione na żywych
    danych, nie w testach.

    W polszczyźnie nazwa własna jest pisana wielką literą, a rzeczownik
    pospolity w środku zdania małą, więc kapitalizacja jest tanim
    i zaskakująco skutecznym filtrem. Kosztem jest pierwszy wyraz zdania
    (i całego nagłówka), który jest kapitalizowany zawsze — ta klasa
    fałszywych trafień zostaje i jest świadomie zaakceptowana: jest o rząd
    wielkości węższa niż „każde wystąpienie słowa w dowolnym miejscu".

    Dotyczy wyłącznie tokenów **nazwy**. Ticker ma własny, ostrzejszy
    warunek (całe słowo wielkimi literami) i tej ścieżki nie używa.
    """
    return {_strip_accents(word) for word in re.findall(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][\w]*", text)}


def content_hash(title: str, published_at: datetime) -> str:
    """Odcisk depeszy do deduplikacji między źródłami.

    Liczony z **tytułu i minuty publikacji**, nie z treści: ta sama
    informacja PAP trafia do Bankiera, Money i StockWatch z identycznym
    tytułem, ale skrótami różnej długości — treść nie jest stabilną
    podstawą porównania, tytuł jest.

    Tytuł normalizujemy (bez ogonków, bez wielkości liter, bez zbitek
    białych znaków), bo wydawcy różnią się interpunkcją i cudzysłowami.
    Datę przycinamy do **minuty**: te same depesze rozchodzą się
    z sekundowym rozjazdem, a dwie różne informacje o identycznym tytule
    w tej samej minucie to zbieg okoliczności, przy którym zwinięcie ich
    w jeden wpis jest zachowaniem właściwym.

    SHA-256, nie skrót kryptograficznie tani: to nie jest ścieżka
    wydajnościowo krytyczna (kilkaset wpisów na przebieg), a kolizja
    oznaczałaby cichą utratę newsu.

    Minuta liczona **zawsze w UTC**. Gdyby hash zależał od strefy czasowej
    procesu, ten sam news dostałby dwa różne odciski na serwerze i na
    laptopie dewelopera — deduplikacja przestałaby działać przy zmianie
    środowiska, cicho i bez błędu.
    """
    normalized_title = " ".join(_tokenize(title))
    minute = published_at.astimezone(UTC).strftime("%Y%m%d%H%M")
    return hashlib.sha256(f"{normalized_title}|{minute}".encode()).hexdigest()
