"""Routing modułu `marketdata`.

Endpointy danych rynkowych (`/markets/{code}/index`, `/assets/search`,
`/assets/{id}`, `/meta/freshness`) przybędą w etapie 4 (plan, kroki 20-24).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
