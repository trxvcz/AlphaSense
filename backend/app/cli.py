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
from datetime import date, datetime
from typing import Literal, cast

import sentry_sdk

from app.core.observability import init_sentry
from app.db.seed import seed_all, seed_reference
from app.db.session import AsyncSessionLocal
from worker.jobs.ingest_market import ingest_market
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
    if args.command in {"ingest", "snapshot"}:
        init_sentry("cli")

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
