"""Routing modułu `portfolio`.

Endpointy portfeli i pozycji (`/portfolios`, `/portfolios/{id}/holdings`,
`/holdings/{id}`, `/portfolios/{id}/summary`, `/portfolios/{id}/valuations`)
przybędą w etapie 5 (plan, kroki 25-27). Każdy endpoint operujący na
konkretnym zasobie korzysta z `Depends(get_owned_portfolio)` /
`Depends(get_owned_holding)` — nigdy z gołego ID z path.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
