"""portfolios holdings_changed_at

Dodaje `portfolios.holdings_changed_at` (etap 5, plan krok 27) — data
ostatniej zmiany składu portfela (dodanie/usunięcie/zmiana ilości
`holdings`). Potrzebne workerowi snapshotów EOD do ustawienia
`PortfolioValuation.composition_change`, gdy dzień snapshotu pokrywa się z
dniem zmiany składu (ADR-101 — dzień zmiany jest wyłączany z serii zwrotów,
żeby dokupienie/sprzedaż nie udawały zysku/straty).

Nullable, bez `server_default` — istniejące wiersze dostają `NULL`
(oznacza „nigdy nie zmieniano po utworzeniu / brak informacji”). Wartość
ustawia logika aplikacyjna w `portfolio/service.py` (poza zakresem tej
migracji — tu tylko kolumna).

Revision ID: a2f2b11877d4
Revises: fc63665c2e00
Create Date: 2026-07-27 09:41:22.146450

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f2b11877d4"
down_revision: str | None = "fc63665c2e00"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Dodaj `portfolios.holdings_changed_at` (DATE, nullable)."""
    op.add_column("portfolios", sa.Column("holdings_changed_at", sa.Date(), nullable=True))


def downgrade() -> None:
    """Usuń `portfolios.holdings_changed_at`."""
    op.drop_column("portfolios", "holdings_changed_at")
