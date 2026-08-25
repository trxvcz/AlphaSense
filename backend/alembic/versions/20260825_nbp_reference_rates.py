"""nbp_reference_rates

Tabela historii stopy referencyjnej NBP (etap 8, plan krok 41a) — wejście do
Sharpe'a w kroku 41b.

Klucz główny to samo `effective_from`: NBP publikuje **zmiany** stopy
(decyzje RPP), a nie szereg dzienny, i w jednym dniu obowiązuje dokładnie
jedna stopa referencyjna. Naturalny klucz jest tu więc jednokolumnowy i nie
potrzeba osobnego `UNIQUE` ani sztucznego `id`.

Klucz główny daje też indeks, który obsługuje jedyne zapytanie odczytowe
(`ORDER BY effective_from DESC LIMIT 1` z `WHERE effective_from <= D`) —
osobny indeks byłby duplikatem.

`ON CONFLICT (effective_from) DO UPDATE` w jobie, nie `DO NOTHING`: NBP
potrafi skorygować opublikowaną wartość, a przy 96 wierszach w całej historii
nadpisanie nic nie kosztuje.

Revision ID: 7a1c4e2b9f38
Revises: c03ad7b7217b
Create Date: 2026-08-25 11:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1c4e2b9f38"
down_revision: str | Sequence[str] | None = "c03ad7b7217b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nbp_reference_rates",
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("effective_from"),
    )


def downgrade() -> None:
    op.drop_table("nbp_reference_rates")
