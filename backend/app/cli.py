"""Punkt wejścia CLI aplikacji (`python -m app.cli <komenda>`), wołane przez
`make seed` (`Makefile`) i (`ingest`/`snapshot`, plan kroki 23/27) ręcznie do
weryfikacji jobów EOD bez czekania na harmonogram workera.

`argparse` (stdlib) świadomie zamiast `typer`/`click` — dodanie zależności
zewnętrznej po to, by sparsować kilka słów z `sys.argv`, byłoby przerostem
formy (CLAUDE.md #10: nowa zależność wymaga pytania użytkownika, więc
unikamy jej, gdy starczy stdlib). `argparse.add_subparsers` już obsługuje
wiele komend/opcji bez migracji na inną bibliotekę.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from typing import Literal, cast

import sentry_sdk

from app.core.config import get_settings
from app.core.observability import init_sentry
from app.db.seed import seed_all, seed_reference
from app.db.session import AsyncSessionLocal
from app.modules.portfolio.repository import held_asset_price_coverage
from app.modules.portfolio.service import today as today_utc
from worker.jobs.ingest_market import backfill_prices, ingest_market
from worker.jobs.snapshot_portfolios import snapshot_portfolios


async def _run_seed(*, reference_only: bool) -> None:
    if reference_only:
        async with AsyncSessionLocal() as session:
            markets = await seed_reference(session)
        print(f"Zasiano słownik rynków ({markets}) i indeksy referencyjne. Bez danych demo.")
        print("Pamiętaj o restarcie workera — joby EOD czyta raz przy starcie (ADR-102).")
        return

    async with AsyncSessionLocal() as session:
        result = await seed_all(session)

    # `print`, nie `structlog` (docs/konwencje.md „nigdy print" dotyczy kodu
    # serwisowego/produkcyjnego) — to jednorazowy komunikat dewelopera z
    # komendy CLI uruchamianej ręcznie w dev (`make seed`), analogicznie do
    # `manage.py createsuperuser` w Django. Wypisanie wygenerowanego hasła
    # demo użytkownika tutaj jest zamierzone i pożądane (zadanie kroku 19).
    print(f"Zasiano dane. Demo użytkownik: {result.demo_user_email}")
    if result.demo_password is not None:
        print(
            f"Hasło demo użytkownika (zapisz teraz, nie zostanie wypisane ponownie): {result.demo_password}"
        )
    else:
        print("Demo użytkownik już istniał — hasło pozostaje niezmienione.")


_ALERT_LEVELS = ("error", "warning", "info")


def _run_alert(*, message: str, level: str, fingerprint: str) -> int:
    """Wysyła pojedyncze zdarzenie do Sentry (plan krok 38).

    Istnieje dla skryptów infrastrukturalnych z HOSTA — `infra/backup/backup.sh`
    i `restore-test.sh` — które muszą zaalarmować, a nie mają jak: DSN, `release`
    i `environment` są konfiguracją aplikacji (`core/observability.py`), a
    składanie koperty Sentry `curl`-em w bashu oznaczałoby drugie, rozjeżdżające
    się miejsce z tą wiedzą.

    `fingerprint` jest obowiązkowy i pochodzi od wołającego: powtarzalna awaria
    backupu ma być JEDNYM problemem z licznikiem, a nie nową sprawą każdej nocy
    (ta sama zasada, co przy alertach ingestii — `worker/jobs/ingest_market.py`).
    """
    if not init_sentry("infra"):
        print(
            "Sentry wyłączone (pusty SENTRY_DSN) — alert nie został wysłany.",
            file=sys.stderr,
        )
        # Zero, nie błąd: pusty DSN to poprawna konfiguracja (dev, wdrożenie bez
        # Sentry). Kod wyjścia tej komendy mówi „czy udało się zaalarmować",
        # a wołający i tak kończy się własnym niezerowym kodem.
        return 0

    with sentry_sdk.new_scope() as scope:
        scope.set_tag("source", "infra-script")
        scope.fingerprint = [fingerprint]
        # `cast`, bo argparse pilnuje `choices=_ALERT_LEVELS`, ale typ z
        # `Namespace` to zwykły `str`.
        sentry_sdk.capture_message(message, level=cast(Literal["error", "warning", "info"], level))

    # Proces kończy się natychmiast po tej linii — bez jawnego `flush` zdarzenie
    # zostałoby w kolejce transportu i alert nigdy by nie doleciał.
    sentry_sdk.flush(timeout=5.0)
    # Symetrycznie do gałęzi wyżej: kod wyjścia jest w obu przypadkach zerowy,
    # więc wołający skrypt (`infra/backup/*.sh`) rozróżnia „wysłane" od
    # „Sentry wyłączone" wyłącznie po tej linii w logu.
    print(f"Alert wysłany do Sentry (poziom {level}, fingerprint {fingerprint}).", file=sys.stderr)
    return 0


async def _run_backfill(
    *,
    start: date,
    end: date,
    market_codes: list[str] | None,
    symbols: list[str] | None,
    provider: str | None = None,
) -> int:
    """Raportuje KAŻDY cel, nie tylko te z danymi — pytanie operatora brzmi
    „czego brakuje", a lista samych sukcesów na nie nie odpowiada.

    Zwraca 1, gdy którakolwiek seria wyszła z dwiema konwencjami `close_adj`:
    dane są wtedy do wyrzucenia i pobrania ponownie z jednego dostawcy
    (`--provider`), a nie do liczenia na nich metryk. Zerowy kod przy takim
    stanie oznaczałby, że skrypt/CI przejdzie dalej po cichu.
    """
    async with AsyncSessionLocal() as session:
        targets = await backfill_prices(
            session,
            start=start,
            end=end,
            market_codes=market_codes,
            symbols=symbols,
            provider=provider,
        )

    if not targets:
        print(
            "Nie było CZEGO zaciągać — żaden cel nie pasuje do podanych filtrów. Sprawdź "
            "kolejno: czy rynek/symbol istnieje w słowniku, czy aktywo jest aktywne, czy "
            "podany `--provider` w ogóle jest w łańcuchu tego rynku.",
            file=sys.stderr,
        )
        return 1

    with_data = [t for t in targets if not t.is_empty]
    print(
        f"Backfill {start.isoformat()} .. {end.isoformat()} — "
        f"{len(with_data)} z {len(targets)} celów ma dane:"
    )
    for target in sorted(targets, key=lambda t: t.label):
        if target.unavailable:
            state = "DOSTAWCA NIEDOSTĘPNY (brak mapowania albo odmowa)"
        elif target.is_empty:
            state = "brak danych"
        else:
            state = f"+{target.rows_added} nowych, {target.rows_after} w bazie"
        if target.windows_failed and not target.unavailable:
            state += f" [{target.windows_failed}/{target.windows_total} okien bez danych]"
        print(f"  {target.label:<12} {state}")

    if not with_data:
        # Powtórzony backfill na komplecie danych daje `rows_added == 0` i jest
        # sukcesem — dlatego progiem jest „ŻADEN cel nie ma wierszy w bazie",
        # nie „nic nie przybyło".
        print(
            "\nNie zaciągnięto ŻADNYCH danych — żaden cel nie ma wierszy w bazie za ten "
            "zakres. Sprawdź kolejno: czy aktywo ma wiersz w `asset_source_map` dla tego "
            "dostawcy, czy dostawca odpowiada (skill `data-provider`, sekcja „Gdy dane "
            "wyglądają źle”).",
            file=sys.stderr,
        )
        return 1

    mixed = [t for t in targets if t.diagnostics is not None and t.diagnostics.mixed_convention]
    if mixed:
        print(
            "\nBLOKADA: poniższe serie mają wiersze w DWÓCH konwencjach `close_adj` "
            "(yfinance koryguje o dywidendy i splity, Stooq/Finnhub/Binance ustawiają "
            "`close_adj := close`). Na styku powstaje skok nieodróżnialny od ruchu ceny, "
            "a wycena i wykresy idą po `close_adj` (CLAUDE.md #3.4). Usuń te wiersze i "
            "pobierz zakres ponownie z jednym dostawcą (`--provider`):",
            file=sys.stderr,
        )
        for target in sorted(mixed, key=lambda t: t.label):
            diagnostics = target.diagnostics
            assert diagnostics is not None  # zawężenie typu — filtr wyżej to gwarantuje
            sources = ", ".join(s or "(brak)" for s in diagnostics.sources)
            print(
                f"  {target.label:<12} {diagnostics.adjusted_rows} skorygowanych / "
                f"{diagnostics.unadjusted_rows} nieskorygowanych, źródła: {sources}",
                file=sys.stderr,
            )
        return 1

    print("Sprawdź jakość serii przed liczeniem metryk: `make seed-history` dopiero potem.")
    return 0


async def _run_seed_history(
    *, start: date, end: date, include_weekends: bool, allow_incomplete: bool = False
) -> int:
    """Odtwarza `portfolio_valuations` dzień po dniu, wołając produkcyjny job
    `snapshot_portfolios(run_date)` — a nie drugą, równoległą implementację
    wyceny, która rozjechałaby się z pierwszą przy najbliższej zmianie
    w `portfolio_service.current_value`.

    **Historia wychodzi SYNTETYCZNA i tylko tak wolno ją opisywać.**
    `snapshot_portfolios` wycenia portfel w DZISIEJSZYM składzie cenami
    z podanego dnia, a `composition_change` bierze z
    `portfolio.holdings_changed_at == run_date`. Wynik odpowiada więc na
    pytanie „ile byłby wart dzisiejszy skład w przeszłości”, a nie „ile
    portfel był wart” — tej drugiej odpowiedzi aplikacja z definicji nie zna
    (ADR-101, snapshoty są append-only i historia nie jest przeliczana).
    Praktyczna konsekwencja: `composition_change` wyjdzie prawie wszędzie
    `false`, więc te dane NIE ćwiczą zrywania ogniwa z kroku 40 — od tego są
    testy jednostkowe na syntetycznych seriach.

    Dlatego komenda jest zablokowana poza `ENV=dev`: na produkcji dopisałaby
    do `portfolio_valuations` wiersze, których nikt nigdy nie zmierzył,
    nieodróżnialne potem od prawdziwych snapshotów.

    Drugi guard dotyczy dolnej granicy zakresu: silnik wyceny POMIJA pozycję
    bez ceny (nie liczy jej jako zero), więc dzień bez kompletu notowań daje
    wycenę cząstkową — a `portfolio_valuations` jest append-only i takiego
    wiersza nie da się potem odróżnić od pełnego. Seria zaczynałaby się
    blisko zera i skakała w miarę „pojawiania się" pozycji: krok 40
    policzyłby z tego absurdalny zwrot, krok 41 — drawdown bliski 100%.
    `allow_incomplete=True` przepuszcza to świadomie (guard jest
    zabezpieczeniem, nie zakazem).
    """
    settings = get_settings()
    if settings.env != "dev":
        print(
            f"ODMOWA: `seed-history` działa wyłącznie przy ENV=dev (jest {settings.env!r}). "
            "Komenda dopisuje do `portfolio_valuations` wyceny odtworzone wstecz — na "
            "produkcji byłyby nieodróżnialne od prawdziwych snapshotów i łamałyby ADR-101.",
            file=sys.stderr,
        )
        return 2

    if start > end:
        print(
            f"ODMOWA: początek zakresu ({start.isoformat()}) jest po jego końcu "
            f"({end.isoformat()}).",
            file=sys.stderr,
        )
        return 2

    async with AsyncSessionLocal() as session:
        coverage = await held_asset_price_coverage(session)

    if not allow_incomplete:
        if coverage.assets_without_prices:
            print(
                "ODMOWA: te trzymane pozycje nie mają w bazie ANI JEDNEGO notowania: "
                f"{', '.join(coverage.assets_without_prices)}. Każda wycena wstecz byłaby "
                "o nie zaniżona, a wiersze `portfolio_valuations` są append-only (ADR-101) "
                "— nie da się ich potem odróżnić od pełnych. Uruchom najpierw "
                "`make backfill`, albo wymuś świadomie flagą --allow-incomplete.",
                file=sys.stderr,
            )
            return 2
        if coverage.first_full_date is not None and start < coverage.first_full_date:
            print(
                f"ODMOWA: pełne pokrycie cenami zaczyna się dopiero "
                f"{coverage.first_full_date.isoformat()}, a zakres startuje "
                f"{start.isoformat()}. Wcześniejsze dni dałyby wyceny cząstkowe "
                "(pozycja bez ceny jest pomijana, nie liczona jako zero) — krok 40 "
                "policzyłby z tego absurdalny zwrot, krok 41 drawdown bliski 100%. "
                f"Podaj --from {coverage.first_full_date.isoformat()} albo wymuś "
                "świadomie flagą --allow-incomplete.",
                file=sys.stderr,
            )
            return 2

    days = 0
    skipped_weekends = 0
    current = start
    while current <= end:
        # Weekend pomijany domyślnie i to nie jest kosmetyka: wycena czyta
        # ceny przez `max(date) <= D`, więc sobota i niedziela dostałyby
        # wartość z piątku. Seria z 365 „dniami” rocznie zamiast ~252 sesji
        # ROZCIEŃCZA zmienność (dwa dni zerowego zwrotu w każdym tygodniu),
        # a `× √252` w kroku 41 zakłada obserwacje sesyjne. Święta zostają
        # (mniejszy błąd, wymagałyby kalendarza per rynek).
        if not include_weekends and current.weekday() >= 5:
            skipped_weekends += 1
            current += timedelta(days=1)
            continue
        await snapshot_portfolios(current)
        days += 1
        current += timedelta(days=1)

    print(
        f"Odtworzono snapshoty dla {days} dni ({start.isoformat()} .. {end.isoformat()}), "
        f"pominięto {skipped_weekends} dni weekendowych."
    )
    print(
        "UWAGA: to historia SYNTETYCZNA — dzisiejszy skład wyceniony cenami z przeszłości. "
        "Nadaje się do ćwiczenia metryk, nie do wniosków o przeszłych wynikach."
    )
    # Ostrzegamy tylko wtedy, gdy flaga FAKTYCZNIE coś przepuściła — inaczej
    # `--allow-incomplete` na komplecie danych straszyłby bez powodu i
    # nauczyłby ignorować ten komunikat.
    if allow_incomplete and (
        coverage.assets_without_prices
        or (coverage.first_full_date is not None and start < coverage.first_full_date)
    ):
        print(
            "UWAGA: --allow-incomplete pominął guard pokrycia cenami — część tych wycen "
            "jest CZĄSTKOWA (pozycje bez notowań zostały pominięte) i nie da się ich "
            "potem odróżnić od pełnych.",
            file=sys.stderr,
        )
    return 0


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"data musi być w formacie YYYY-MM-DD: {value!r}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser(
        "seed", help="Zasiej słownik rynków, demo aktywa i demo użytkownika z portfelem"
    )
    seed_parser.add_argument(
        "--reference-only",
        action="store_true",
        help=(
            "Tylko dane słownikowe: rynki, indeksy referencyjne i ich mapowania na dostawców. "
            "Bez demo użytkownika, demo portfela i demo pozycji — wariant PRODUKCYJNY "
            "(make prod-seed, docs/wdrozenie.md)"
        ),
    )

    ingest_parser = subparsers.add_parser(
        "ingest",
        help=(
            "Uruchom ręcznie job EOD ingestii cen/kursów dla jednego rynku "
            "(bez czekania na harmonogram workera, plan krok 23)"
        ),
    )
    ingest_parser.add_argument(
        "--market",
        required=True,
        dest="market_code",
        help="Kod rynku (`markets.code`, np. GPW, FX)",
    )
    ingest_parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        dest="run_date",
        help="Dzień do zaingestowania (YYYY-MM-DD); domyślnie dziś w strefie czasowej rynku",
    )

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help=(
            "Uruchom ręcznie job snapshotów wyceny portfeli (bez czekania na "
            "automatyczne wywołanie po ingestii EOD, plan krok 27)"
        ),
    )
    snapshot_parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        dest="run_date",
        help="Dzień snapshotu (YYYY-MM-DD); domyślnie dziś (`portfolio_service.today()`)",
    )

    backfill_parser = subparsers.add_parser(
        "backfill-prices",
        help=(
            "Zaciągnij historię cen i kursów za dłuższy okres (etap 8, krok zerowy) "
            "— jednorazowo, poza harmonogramem workera"
        ),
    )
    backfill_parser.add_argument(
        "--from",
        required=True,
        type=_parse_date,
        dest="start",
        help="Początek zakresu (YYYY-MM-DD)",
    )
    backfill_parser.add_argument(
        "--to",
        type=_parse_date,
        default=None,
        dest="end",
        help="Koniec zakresu (YYYY-MM-DD); domyślnie dziś",
    )
    backfill_parser.add_argument(
        "--market",
        action="append",
        default=None,
        dest="market_codes",
        help="Kod rynku, można powtórzyć (np. --market GPW --market FX); domyślnie wszystkie",
    )
    backfill_parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        dest="symbols",
        help="Symbol aktywa lub waluta, można powtórzyć; domyślnie wszystkie z wybranych rynków",
    )
    backfill_parser.add_argument(
        "--provider",
        default=None,
        help=(
            "Przypnij przebieg do jednego dostawcy (np. --provider yfinance) zamiast "
            "łańcucha fallbacku. Bez tego łańcuch rozstrzyga się per okno i jedna seria "
            "może powstać z dwóch niekompatybilnych konwencji `close_adj`"
        ),
    )

    history_parser = subparsers.add_parser(
        "seed-history",
        help=(
            "TYLKO DEV: odtwórz `portfolio_valuations` wstecz, żeby metryki etapu 8 "
            "miały szereg czasowy do liczenia"
        ),
    )
    history_parser.add_argument(
        "--from",
        required=True,
        type=_parse_date,
        dest="start",
        help="Pierwszy dzień historii (YYYY-MM-DD)",
    )
    history_parser.add_argument(
        "--to",
        type=_parse_date,
        default=None,
        dest="end",
        help="Ostatni dzień historii (YYYY-MM-DD); domyślnie dziś",
    )
    history_parser.add_argument(
        "--include-weekends",
        action="store_true",
        help=(
            "Licz snapshoty także w soboty i niedziele. Domyślnie pomijane — patrz "
            "`_run_seed_history`, weekendy rozcieńczają zmienność"
        ),
    )
    history_parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Licz snapshoty także dla dni bez kompletu notowań wszystkich trzymanych "
            "pozycji. Domyślnie zablokowane — wyceny cząstkowe są append-only i "
            "nieodróżnialne potem od pełnych (patrz `_run_seed_history`)"
        ),
    )

    alert_parser = subparsers.add_parser(
        "alert",
        help=(
            "Wyślij zdarzenie do Sentry — dla skryptów z hosta, które nie mają "
            "dostępu do konfiguracji aplikacji (infra/backup/*.sh, plan krok 38)"
        ),
    )
    alert_parser.add_argument("--message", required=True, help="Treść zdarzenia")
    alert_parser.add_argument(
        "--level",
        default="error",
        choices=_ALERT_LEVELS,
        help="Poziom zdarzenia w Sentry (domyślnie error)",
    )
    alert_parser.add_argument(
        "--fingerprint",
        required=True,
        help=(
            "Klucz grupowania w Sentry, np. `backup-failed`. Powtarzalna awaria "
            "ma być jednym problemem z licznikiem, nie nową sprawą co dobę"
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "alert":
        return _run_alert(message=args.message, level=args.level, fingerprint=args.fingerprint)

    if args.command == "seed":
        asyncio.run(_run_seed(reference_only=args.reference_only))
        return 0

    # Krok 37: ręczne uruchomienie joba raportuje do Sentry tak samo jak
    # automatyczne — inaczej `python -m app.cli ingest` na produkcji byłby
    # ślepą plamą. `seed` pomijamy świadomie: to komenda administracyjna
    # uruchamiana pod okiem człowieka, jej błąd i tak ląduje na konsoli.
    if args.command in {"ingest", "snapshot", "backfill-prices", "seed-history"}:
        init_sentry("cli")

    if args.command == "backfill-prices":
        try:
            return asyncio.run(
                _run_backfill(
                    start=args.start,
                    end=args.end or today_utc(),
                    market_codes=args.market_codes,
                    symbols=args.symbols,
                    provider=args.provider,
                )
            )
        except Exception as exc:  # noqa: BLE001 — diagnostyczne narzędzie CLI, nie handler HTTP
            # Błędy pojedynczych okien/aktywów są łapane w `backfill_prices`
            # (skill `job-eod`, reguła 6) — tu ląduje tylko porażka całości,
            # np. baza nieosiągalna albo zły zakres dat.
            print(f"BŁĄD: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "seed-history":
        try:
            return asyncio.run(
                _run_seed_history(
                    start=args.start,
                    end=args.end or today_utc(),
                    include_weekends=args.include_weekends,
                    allow_incomplete=args.allow_incomplete,
                )
            )
        except Exception as exc:  # noqa: BLE001 — diagnostyczne narzędzie CLI, nie handler HTTP
            print(f"BŁĄD: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    if args.command == "ingest":
        try:
            status = asyncio.run(ingest_market(args.market_code, args.run_date))
        except Exception as exc:  # noqa: BLE001 — diagnostyczne narzędzie CLI, nie handler HTTP
            # Porażka poza pętlą per-aktywo/waluta (patrz `ingest_market.py`,
            # gałąź `except Exception` w `_run_ingestion`) — `IngestionRun`
            # jest już zapisany, tu tylko przekładamy na exit code.
            print(f"BŁĄD: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        # `status is None` = nic się nie wydarzyło (nieznany rynek, blokada
        # zajęta przez inny proces) — nie jest to porażka ingestii samej w
        # sobie, więc exit 0; tylko "failed" (SKILL `job-eod`: "niepowodzenie
        # całości = alert") jest błędem ze stanowiska skryptu/CI.
        return 1 if status == "failed" else 0

    if args.command == "snapshot":
        try:
            asyncio.run(snapshot_portfolios(args.run_date))
        except Exception as exc:  # noqa: BLE001 — diagnostyczne narzędzie CLI, nie handler HTTP
            # Porażka poza pętlą per-portfel (np. baza odmawia połączenia
            # przy `list_all_portfolios`) — błędy pojedynczych portfeli
            # `snapshot_portfolios` już łapie i loguje sama, nigdy nie
            # rzuca ich tutaj (SKILL `job-eod` reguła 6).
            print(f"BŁĄD: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(
        f"Nieznana komenda: {args.command}"
    )  # pragma: no cover — argparse to wyłapuje wcześniej
    return 2


if __name__ == "__main__":
    sys.exit(main())
