"""Punkt wejścia CLI aplikacji (`python -m app.cli <komenda>`), wołane przez
`make seed` (`Makefile`).

`argparse` (stdlib) świadomie zamiast `typer`/`click`: jest dziś tylko jedna
komenda (`seed`) bez własnych opcji — dodanie zależności zewnętrznej po to,
by sparsować jedno słowo z `sys.argv`, byłoby przerostem formy (CLAUDE.md #10:
nowa zależność wymaga pytania użytkownika, więc unikamy jej, gdy starczy
stdlib). Jeśli w kolejnych krokach planu (np. `flush-cache`, `recalculate`)
komend i opcji przybędzie, `argparse.add_subparsers` już to obsłuży bez
migracji na inną bibliotekę.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.db.seed import seed_all
from app.db.session import AsyncSessionLocal


async def _run_seed() -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "seed", help="Zasiej słownik rynków, demo aktywa i demo użytkownika z portfelem"
    )

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(_run_seed())
        return 0

    parser.error(
        f"Nieznana komenda: {args.command}"
    )  # pragma: no cover — argparse to wyłapuje wcześniej
    return 2


if __name__ == "__main__":
    sys.exit(main())
