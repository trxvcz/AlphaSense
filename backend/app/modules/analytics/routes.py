"""Routing modułu `analytics`.

Endpointy analityki struktury (`/portfolios/{id}/allocation`,
`/portfolios/{id}/concentration`, `/portfolios/{id}/markets`) przybędą
w etapie 6 (plan, kroki 29-30) — serce produktu. Ryzyko i wyniki
(`/portfolios/{id}/risk`, `/portfolios/{id}/performance`) to Faza 2
(plan, krok 41 i dalej).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
