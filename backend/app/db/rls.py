"""Kontekst użytkownika dla Row Level Security (ADR-002 warstwa 3, krok 44).

**Dlaczego `SET LOCAL` (`set_config(..., is_local => true)`), a nie zwykłe
`SET`:** pula połączeń async SQLAlchemy oddaje to samo połączenie kolejnym
żądaniom. Ustawienie sesyjne przeżyłoby zwrot połączenia do puli i następny
użytkownik odziedziczyłby `app.user_id` poprzedniego — czyli dokładnie ten
wyciek, przed którym RLS ma bronić. Ustawienie transakcyjne znika przy
`COMMIT`/`ROLLBACK`, więc nie ma czego dziedziczyć.

**Dlaczego listener na zdarzeniu `begin`, a nie jednorazowe ustawienie
w `get_db`:** `SET LOCAL` żyje do końca **transakcji**, a jedno żądanie robi
ich kilka (serwisy commitują same). Ustawione raz przy otwarciu sesji
zniknęłoby po pierwszym commicie i kolejne zapytania tego samego żądania
zobaczyłyby zero wierszy. Listener wpina się w każdą transakcję i odczytuje
wartość z `ContextVar`, który jest per zadanie asyncio — czyli per żądanie.

`ContextVar` bez wartości → pusty string → `NULLIF(...)::uuid` w politykach
daje `NULL` → **zero wierszy**. Domyślną odpowiedzią na brak kontekstu jest
niewidoczność danych, nie ich udostępnienie.
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

# Pusty string, nie `None`: `set_config` przyjmuje tylko tekst, a pusty
# string jest wartością, którą polityki tłumaczą na `NULL` (patrz migracja
# `20260826_rls_policies.py`).
_NO_USER = ""

current_user_id: ContextVar[str] = ContextVar("app_user_id", default=_NO_USER)


def set_current_user_id(user_id: UUID | None) -> None:
    """Ustawia właściciela bieżącego żądania. Wołane raz, przez
    `get_current_user` — czyli w jedynym miejscu, które wie, kto pyta."""
    current_user_id.set(str(user_id) if user_id is not None else _NO_USER)


async def bind_session_user(db: AsyncSession, user_id: UUID) -> None:
    """Ustawia właściciela dla `db` **i dla już otwartej transakcji**.

    Sam `ContextVar` nie wystarczy: listener `begin` wpina wartość przy
    **rozpoczęciu** transakcji, a `get_current_user` bywa wołane, gdy jakaś
    transakcja już trwa (np. po odczycie, który jej nie potrzebował).
    Wtedy `SET LOCAL` z listenera już się wydarzył — z pustą wartością — i
    kolejne zapytania tego samego żądania widziałyby zero wierszy zamiast
    danych właściciela. Stąd jawne `set_config` tutaj, obok `ContextVar`
    obsługującego wszystkie następne transakcje.
    """
    set_current_user_id(user_id)
    await db.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)}
    )


def register_rls_listener(engine: Engine) -> None:
    """Wpina ustawianie `app.user_id` w każdą transakcję tego silnika.

    Argumentem jest **synchroniczny** silnik (`AsyncEngine.sync_engine`) —
    warstwa zdarzeń SQLAlchemy działa na nim, a nie na opakowaniu async.
    """

    @event.listens_for(engine, "begin")
    def _set_user_id(conn: Connection) -> None:
        # Parametryzowane, nie sklejane: `app.user_id` pochodzi z tokenu,
        # więc jest danymi z zewnątrz jak każde inne. `text()`, nie
        # `exec_driver_sql`: sterownik asyncpg nie zna stylu `%s`.
        conn.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": current_user_id.get()},
        )
