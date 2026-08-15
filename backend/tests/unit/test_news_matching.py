"""Testy dopasowania newsów do aktywów i deduplikacji (krok 46, etap 9).

Czysta logika tekstowa — bez bazy i bez sieci, na przykładach wziętych
z realnych tytułów feedów Bankiera i Money.

Sedno tych testów to **fałszywe dopasowania**, nie prawdziwe. Heurystyka,
która tagguje wszystko, jest bezużyteczna dokładnie tak samo jak taka,
która nie tagguje niczego — a łatwiej ją przeoczyć, bo „newsy się
pokazują".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from app.modules.news.matching import build_matcher, content_hash, match_assets

_CDR = uuid4()
_PKN = uuid4()
_KGHM = uuid4()


def _matchers() -> list:
    return [
        build_matcher(_CDR, "CDR", "CD Projekt SA"),
        build_matcher(_PKN, "PKN", "Orlen SA"),
        build_matcher(_KGHM, "KGHM", "KGHM Polska Miedź SA"),
    ]


class TestBuildMatcher:
    def test_odrzuca_stopwords_i_krotkie_tokeny(self) -> None:
        """„CD Projekt SA" → tylko „projekt": „CD" za krótkie, „SA" bez treści."""
        matcher = build_matcher(_CDR, "CDR", "CD Projekt SA")
        assert matcher.name_tokens == ("projekt",)

    def test_usuwa_ogonki(self) -> None:
        """„Miedź" musi dać się dopasować do „miedz" z feedu bez ogonków."""
        matcher = build_matcher(_KGHM, "KGHM", "KGHM Polska Miedź SA")
        assert "miedz" in matcher.name_tokens

    def test_nazwa_z_samych_slow_pospolitych_daje_pusta_liste(self) -> None:
        """Takie aktywo ma być rozpoznawalne wyłącznie po tickerze."""
        matcher = build_matcher(uuid4(), "ETFX", "ETF Fundusz SA")
        assert matcher.name_tokens == ()

    def test_l_z_kreska_nie_rozcina_wyrazu(self) -> None:
        """Regresja ze znaleziska na żywych danych.

        „ł" nie jest literą bazową z diakrytykiem, więc NFKD go nie rozkłada.
        Bez jawnej podmiany „Złoto" rozpadało się na „z" + „oto", a „oto"
        jest pospolitym polskim słowem — aktywo XAU tagowało się do
        artykułów zawierających „Oto gdzie szukać...".
        """
        matcher = build_matcher(uuid4(), "XAU", "Złoto")
        assert matcher.name_tokens == ("zloto",)

    def test_token_czysto_liczbowy_odpada(self) -> None:
        """Regresja: „NASDAQ 100" dawało token `100`, pasujący do każdej setki."""
        matcher = build_matcher(uuid4(), "^NDX", "NASDAQ 100")
        assert matcher.name_tokens == ("nasdaq",)


class TestMatchAssets:
    def test_dopasowanie_po_nazwie(self) -> None:
        matched = match_assets("Orlen podnosi prognozy na 2026 rok", None, _matchers())
        assert matched == [_PKN]

    def test_dopasowanie_po_tickerze_wielkimi_literami(self) -> None:
        matched = match_assets("Rekomendacja: KGHM z ceną docelową 180 zł", None, _matchers())
        assert matched == [_KGHM]

    def test_ticker_malymi_literami_nie_lapie(self) -> None:
        """Wielkość liter jest jedynym, co odróżnia ticker od zwykłego wyrazu.

        „cdr" w zdaniu to nie jest wzmianka o CD Projekcie.
        """
        matched = match_assets("plik cdr do pobrania", None, _matchers())
        assert matched == []

    def test_token_w_srodku_wyrazu_nie_lapie(self) -> None:
        """Dopasowanie po całych wyrazach, nie po podciągach.

        Bez tego „projekt" łapałoby „projektowanie", a „Orlen" —
        „Orlenu" byłoby OK, ale „zaprojektowany" już nie.
        """
        matched = match_assets("Nowe projektowanie wnętrz w Warszawie", None, _matchers())
        assert matched == []

    def test_szuka_takze_w_skrocie_nie_tylko_w_tytule(self) -> None:
        matched = match_assets(
            "Spółka podnosi prognozy",
            "Zarząd Orlen poinformował o rewizji planu.",
            _matchers(),
        )
        assert matched == [_PKN]

    def test_jeden_news_moze_dotyczyc_wielu_aktywow(self) -> None:
        matched = match_assets("KGHM i Orlen w indeksie WIG20", None, _matchers())
        assert set(matched) == {_PKN, _KGHM}

    def test_brak_wzmianki_daje_pusta_liste(self) -> None:
        matched = match_assets("Kurs euro najniżej od miesiąca", None, _matchers())
        assert matched == []

    def test_indeks_nie_lapie_sie_po_samej_liczbie(self) -> None:
        """Regresja: „FTSE 100" tagowało artykuł o oprocentowaniu konta.

        Token `100` z nazwy indeksu pasował do każdej setki w tekście.
        """
        ftse = uuid4()
        matchers = [build_matcher(ftse, "^FTSE", "FTSE 100")]
        assert match_assets("Bank podnosi oprocentowanie do 100 tys. zł", None, matchers) == []
        assert match_assets("FTSE 100 z nowym rekordem", None, matchers) == [ftse]

    def test_ticker_indeksu_lapie_sie_mimo_daszka_w_symbolu(self) -> None:
        """Regresja: symbole indeksów (`^NDX`, `^GDAXI`) nie dopasowywały się
        po tickerze **w żadnym przypadku**.

        `\\b` przed `^` nie jest granicą słowa (oba znaki są niesłowne), więc
        nawet dosłowne „^NDX" w tekście wracało z `findall` jako `NDX`
        i porównanie z `^NDX` dawało `False`. Indeksy zagraniczne rozpoznawały
        się wyłącznie po członie nazwy — czego stary test na „FTSE 100" nie
        odróżniał, bo tam trafiał token nazwy `ftse`, nie ticker.

        Nazwa jest tu celowo bez wspólnego członu z tickerem, żeby jedyną
        drogą dopasowania został ticker.
        """
        ndx = uuid4()
        matchers = [build_matcher(ndx, "^NDX", "Indeks technologiczny")]
        assert match_assets("NDX zamknął się wyżej", None, matchers) == [ndx]
        assert match_assets("^NDX zamknął się wyżej", None, matchers) == [ndx]
        assert match_assets("Spokojna sesja na parkiecie", None, matchers) == []

    def test_nazwa_pospolita_mala_litera_nie_lapie(self) -> None:
        """Regresja: „CD Projekt" tagowało się do „projekt ustawy".

        Token `projekt` z nazwy spółki jest zwyczajnym polskim rzeczownikiem.
        Rozróżnia je kapitalizacja — nazwa własna wielką literą, pospolity
        rzeczownik w środku zdania małą.
        """
        assert match_assets("Jest projekt ustawy o refundacji pomp", None, _matchers()) == []

    def test_nazwa_wlasna_wielka_litera_lapie(self) -> None:
        assert match_assets("Nowa gra studia Projekt trafia na rynek", None, _matchers()) == [_CDR]

    def test_zloto_nie_lapie_sie_na_slowo_oto(self) -> None:
        """Regresja: rozcięcie „Złoto" na „z"+„oto" tagowało pół feedu."""
        xau = uuid4()
        matchers = [build_matcher(xau, "XAU", "Złoto")]
        assert match_assets("Oto gdzie szukać okazji na GPW", None, matchers) == []
        assert match_assets("Złoto drożeje trzeci dzień z rzędu", None, matchers) == [xau]


class TestContentHash:
    def test_ten_sam_tytul_i_minuta_daje_ten_sam_hash(self) -> None:
        """Sedno deduplikacji: ta sama depesza PAP z trzech serwisów."""
        moment = datetime(2026, 8, 10, 12, 30, 0, tzinfo=UTC)
        assert content_hash("Orlen podnosi prognozy", moment) == content_hash(
            "Orlen podnosi prognozy", moment
        )

    def test_rozjazd_sekundowy_nie_zmienia_hasha(self) -> None:
        """Serwisy publikują tę samą depeszę z kilkusekundowym poślizgiem."""
        moment = datetime(2026, 8, 10, 12, 30, 5, tzinfo=UTC)
        later = datetime(2026, 8, 10, 12, 30, 47, tzinfo=UTC)
        assert content_hash("Orlen podnosi prognozy", moment) == content_hash(
            "Orlen podnosi prognozy", later
        )

    def test_interpunkcja_i_wielkosc_liter_nie_zmieniaja_hasha(self) -> None:
        moment = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
        assert content_hash("Orlen: podnosi prognozy!", moment) == content_hash(
            "ORLEN PODNOSI PROGNOZY", moment
        )

    def test_hash_nie_zalezy_od_strefy_czasowej_zapisu(self) -> None:
        """Ten sam moment w czasie, dwa różne zapisy strefowe.

        Gdyby hash liczył się w czasie lokalnym procesu, deduplikacja
        rozjechałaby się między serwerem a laptopem — cicho, bez błędu.
        """
        utc = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
        warsaw = datetime(2026, 8, 10, 14, 30, tzinfo=timezone(timedelta(hours=2)))
        assert content_hash("Orlen podnosi prognozy", utc) == content_hash(
            "Orlen podnosi prognozy", warsaw
        )

    def test_rozne_tytuly_daja_rozne_hashe(self) -> None:
        moment = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
        assert content_hash("Orlen podnosi prognozy", moment) != content_hash(
            "KGHM podnosi prognozy", moment
        )

    def test_ta_sama_depesza_innego_dnia_to_inny_news(self) -> None:
        first = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
        second = datetime(2026, 8, 11, 12, 30, tzinfo=UTC)
        assert content_hash("Orlen podnosi prognozy", first) != content_hash(
            "Orlen podnosi prognozy", second
        )
