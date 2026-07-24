"""initial empty

Pusta migracja startowa — infrastruktura Alembic (etap 1, plan krok 8).
Wygenerowana przez `alembic revision --autogenerate` na pustym
`Base.metadata` (brak jeszcze modeli ORM — te powstają w etapach 2–3),
dlatego `upgrade()`/`downgrade()` nie zawierają operacji. Kolejne migracje
dopiszą tabele `users`, `portfolios`, `holdings`, `markets`, `assets`, ...

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Brak operacji — nie ma jeszcze żadnych modeli ORM."""


def downgrade() -> None:
    """Downgrade schema. Brak operacji (symetryczne z `upgrade()`)."""
