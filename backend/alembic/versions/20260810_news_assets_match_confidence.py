"""news_assets.match_confidence — skąd pochodzi powiązanie

Revision ID: 50cd089eb951
Revises: 6812ced23486
Create Date: 2026-08-10 21:47:08.580338

Skąd wzięło się powiązanie newsu z aktywem (krok 46, etap 9): `source`
— podał je dostawca pytany o symbol (Finnhub `/company-news`), `heuristic`
— wynik dopasowania polskiego tekstu po naszej stronie (`matching.py`).
UI ma obowiązek pokazać różnicę: pierwsze jest faktem, drugie
przybliżeniem (CLAUDE.md #3.15).

Domyślna wartość `heuristic` jest celowo tą ostrożniejszą — istniejące
wiersze pochodzą z dopasowania tekstu, a pominięcie kolumny przy zapisie
ma zaniżać deklarowaną pewność, nie zawyżać.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50cd089eb951"
down_revision: str | Sequence[str] | None = "6812ced23486"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "news_assets",
        sa.Column(
            "match_confidence", sa.String(), server_default=sa.text("'heuristic'"), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("news_assets", "match_confidence")
