"""Zależności FastAPI współdzielone między modułami.

Szkielet etapu 1. `get_current_user` (weryfikacja JWT) i zależności
izolacji danych `get_owned_portfolio` / `get_owned_holding` (ADR-002,
skill `izolacja-danych`) powstają w etapie 2, plan krok 14. Żaden router
w tym etapie jeszcze z nich nie korzysta — nie ma endpointów.

Zasada na przyszłość: nowy typ zasobu wymagający autoryzacji = nowa
zależność `get_owned_*` w tym pliku, nigdy przyjmowanie gołego ID z path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends


class CurrentUser:
    """Placeholder zalogowanego użytkownika. Pełny model w etapie 2 (auth)."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id


async def get_current_user() -> CurrentUser:
    """Zależność wstrzykująca zalogowanego użytkownika na podstawie JWT.

    Implementacja powstaje w etapie 2. Do tego czasu nieużywana przez
    żaden endpoint.
    """
    raise NotImplementedError("Auth zostanie dodany w etapie 2")


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
