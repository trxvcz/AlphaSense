"""Routing modułu `auth`.

Endpointy (`/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`,
`/auth/google/*`) przybędą w etapie 2 (plan, kroki 11-13). Routes wołają
wyłącznie `service`, nigdy SQL bezpośrednio (patrz skill `fastapi-modul`).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
