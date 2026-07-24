"""Deklaratywna baza modeli SQLAlchemy 2.x.

Wszystkie modele ORM (etapy 2–3: `users`, `portfolios`, `holdings`, `markets`,
`assets`, ...) dziedziczą z `Base`. `Base.metadata` jest jedynym źródłem
prawdy dla `alembic revision --autogenerate` (patrz `alembic/env.py`) —
nigdy nie hardkoduj tu tabel na potrzeby migracji.

Ten szkielet (etap 1, plan krok 8) nie zawiera jeszcze żadnych modeli.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Wspólna klasa bazowa dla wszystkich modeli ORM projektu."""
