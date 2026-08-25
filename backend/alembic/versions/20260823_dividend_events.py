"""dividend_events

Tabela kalendarza dywidend (etap 9, plan krok 47). `docs/model-danych.md:32`
rezerwował ją jako „Faza 3" bez kolumn — schemat powstaje razem z tą migracją.

Zdarzenia dywidendowe nie należą do użytkownika (tak jak `news` i `prices`),
więc żaden FK nie prowadzi do `users`. Izolacja dzieje się przy odczycie:
endpoint zawęża do aktywów portfela zweryfikowanego przez
`get_owned_portfolio`.

`UNIQUE (asset_id, ex_date)` to klucz naturalny zdarzenia i podstawa
idempotentnego `ON CONFLICT DO UPDATE` w jobie — **DO UPDATE, nie DO
NOTHING**: zapowiedziana kwota i data wypłaty bywają korygowane przed
wypłatą, więc świeższa odpowiedź dostawcy wygrywa (odwrotnie niż przy
newsach, gdzie treść depeszy jest niezmienna).

Indeks `(asset_id, ex_date)` rosnąco — kalendarz czyta „najbliższe ex-daty
od dziś w przód", a nie najświeższe wpisy.

Revision ID: c03ad7b7217b
Revises: 50cd089eb951
Create Date: 2026-08-23 07:18:16.240115

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c03ad7b7217b"
down_revision: str | Sequence[str] | None = "50cd089eb951"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dividend_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("declaration_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "ex_date", name="uq_dividend_events_asset_ex"),
    )
    op.create_index(
        "ix_dividend_events_asset_id_ex_date",
        "dividend_events",
        ["asset_id", "ex_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dividend_events_asset_id_ex_date", table_name="dividend_events")
    op.drop_table("dividend_events")
