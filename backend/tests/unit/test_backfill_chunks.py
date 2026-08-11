"""Testy `_date_chunks` z `worker.jobs.ingest_market` (etap 8, krok zerowy).

Czysta matematyka dat — zero bazy, zero sieci, zero mocków (CLAUDE.md §8:
„logika obliczeniowa — testy jednostkowe na znanych liczbach, bez mocków
bazy tam, gdzie obliczenie jest czysto matematyczne").

Stawka jest konkretna: **API NBP odrzuca zakresy dłuższe niż 367 dni**, a
`nbp.py` wkleja granice prosto w URL. Okno o jeden dzień za szerokie kładzie
cały backfill kursów, a bez kursów benchmark `^GSPC` (USD) nie da się
przeliczyć na PLN (decyzja 4 etapu). Druga stawka to komplet: dziura między
oknami = dni bez notowań, których nikt nie zauważy, bo brak danych
historycznych wygląda jak brak sesji.
"""

from __future__ import annotations

from datetime import date, timedelta

from worker.jobs.ingest_market import _BACKFILL_CHUNK_DAYS, _date_chunks

# Limit twardy po stronie NBP — okno MUSI być węższe (`docs` providera).
_NBP_MAX_SPAN_DAYS = 367


def _assert_covers_exactly(start: date, end: date) -> list[tuple[date, date]]:
    """Okna są ciągłe, rozłączne i pokrywają dokładnie `[start, end]`."""
    chunks = list(_date_chunks(start, end))
    assert chunks, f"pusty podział dla {start}..{end}"
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:], strict=False):
        # Dokładnie dzień styku: `+1` to brak dziury, a brak nakładania
        # oszczędza zapytania (upsert i tak jest idempotentny).
        assert next_start == prev_end + timedelta(days=1), f"dziura/nakładka przy {prev_end}"
    for chunk_start, chunk_end in chunks:
        assert chunk_start <= chunk_end
        span = (chunk_end - chunk_start).days + 1
        assert span <= _NBP_MAX_SPAN_DAYS, f"okno {span} dni — NBP odrzuci ({chunk_start})"
    return chunks


def test_single_day_range_gives_one_window() -> None:
    start = date(2026, 8, 10)
    assert _assert_covers_exactly(start, start) == [(start, start)]


def test_range_shorter_than_window_is_not_split() -> None:
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    assert _assert_covers_exactly(start, end) == [(start, end)]


def test_range_exactly_one_window_is_not_split() -> None:
    """Granica: `start + _BACKFILL_CHUNK_DAYS` mieści się w jednym oknie."""
    start = date(2025, 1, 1)
    end = start + timedelta(days=_BACKFILL_CHUNK_DAYS)
    assert _assert_covers_exactly(start, end) == [(start, end)]


def test_range_one_day_past_window_splits_into_two() -> None:
    start = date(2025, 1, 1)
    end = start + timedelta(days=_BACKFILL_CHUNK_DAYS + 1)
    chunks = _assert_covers_exactly(start, end)
    assert len(chunks) == 2
    assert chunks[1] == (end, end)


def test_five_year_range_covers_every_day_without_gaps() -> None:
    """Realny przypadek z decyzji 5 etapu — 5 lat wstecz, ~1250 sesji."""
    start, end = date(2021, 8, 10), date(2026, 8, 10)
    chunks = _assert_covers_exactly(start, end)

    covered = sum((chunk_end - chunk_start).days + 1 for chunk_start, chunk_end in chunks)
    assert covered == (end - start).days + 1


def test_leap_day_inside_window_does_not_exceed_nbp_limit() -> None:
    """Rok przestępny zjada margines między `_BACKFILL_CHUNK_DAYS` a limitem
    NBP — okno liczy dni kalendarzowe, nie „rok"."""
    _assert_covers_exactly(date(2024, 1, 1), date(2024, 12, 31))
    _assert_covers_exactly(date(2023, 3, 1), date(2025, 3, 1))


def test_reversed_range_yields_nothing() -> None:
    """`end` przed `start` daje pusty podział — wołający ma własny guard
    (`backfill_prices` podnosi `ValueError`). Test pilnuje, żeby ta funkcja
    nie zaczęła w takim wypadku produkować okien wstecz.
    """
    assert list(_date_chunks(date(2026, 8, 10), date(2026, 8, 1))) == []
