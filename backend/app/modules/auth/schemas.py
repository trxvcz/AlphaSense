"""Schematy Pydantic modułu `auth` (request/response).

Kwoty nie dotyczą tego modułu — brak `Decimal` tutaj. Hasła nigdy nie
wracają w odpowiedzi (`UserOut` nie zawiera `password_hash`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    """Wejście `POST /auth/register`."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginIn(BaseModel):
    """Wejście `POST /auth/login`."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    """Wyjście publiczne reprezentujące konto — bez `password_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class AccessTokenOut(BaseModel):
    """Wyjście `POST /auth/login` i `POST /auth/refresh` — access token w body.

    Refresh token nigdy nie wraca w body — wyłącznie w httpOnly cookie.
    """

    access_token: str
    token_type: str = "bearer"
