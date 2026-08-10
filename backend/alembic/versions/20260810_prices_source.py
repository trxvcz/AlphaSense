"""prices.source — dostawca wiersza ceny

Dodaje `prices.source` (etap 8, krok zerowy) — nazwa dostawcy, od którego
pochodzi dany wiersz (`yfinance`, `stooq`, `finnhub`, `binance`, `nbp`).

Powód jest merytoryczny, nie diagnostyczny: konwencje `close_adj` między
dostawcami są niekompatybilne. yfinance oddaje realną cenę skorygowaną o
dywidendy i splity, a Stooq/Finnhub/Binance wpisują `close_adj := close`
(patrz docstringi providerów). Łańcuch fallbacku rozstrzyga się per
zapytanie, więc jedna seria potrafi wymieszać obie konwencje — na styku
powstaje skok rzędu kilkunastu procent, którego NIE widać w surowym
`close` (heurystyka splitu z kroku 28 porównuje właśnie `close`, więc go
nie złapie). Kroki 40-42 policzyłyby taki skok jako realny zwrot,
zmienność i drawdown. Bez tej kolumny serii z wymieszaną konwencją nie da
się ani wykryć, ani naprawić punktowo.

Nullable, bez `server_default` — istniejące wiersze dostają `NULL`,
co znaczy „źródło nieznane, wiersz sprzed tej kolumny". Świadomie NIE
zgadujemy źródła wstecz z `asset_source_map`: priorytety dostawców
zmieniały się w czasie (Stooq bywał niedostępny i backfill schodził na
yfinance), więc wpisanie „prawdopodobnego" dostawcy zamieniłoby brak
wiedzy w fałszywą pewność — dokładnie na kolumnie, która ma tę pewność
dawać. Wypełnianie wartości robi warstwa ingestii (`upsert_prices`),
poza zakresem tej migracji.

Revision ID: 926b382d1715
Revises: a2f2b11877d4
Create Date: 2026-08-10 13:24:26.819872

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "926b382d1715"
down_revision: str | None = "a2f2b11877d4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Dodaj `prices.source` (VARCHAR, nullable)."""
    op.add_column("prices", sa.Column("source", sa.String(), nullable=True))


def downgrade() -> None:
    """Usuń `prices.source`.

    Bezstratne dla danych cenowych — kolumna niesie wyłącznie metadane
    pochodzenia. Traci się natomiast możliwość wykrycia serii z
    wymieszaną konwencją `close_adj` (patrz docstring modułu).
    """
    op.drop_column("prices", "source")
