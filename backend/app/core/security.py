"""Bezpieczeństwo: hashowanie haseł i tokeny JWT.

Szkielet etapu 1 — sygnatury są już docelowe, żeby moduł `auth` mógł się
rozwijać bez zmiany interfejsu. Pełna implementacja (hashowanie, JWT
access+refresh, OAuth Google PKCE) powstaje w etapie 2, plan kroki 11-13.
Świadomie brak logiki tutaj.
"""

from __future__ import annotations


def hash_password(plain_password: str) -> str:
    """Zwraca hash hasła. Implementacja w etapie 2 (auth)."""
    raise NotImplementedError("Hashowanie haseł zostanie dodane w etapie 2 (auth)")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Weryfikuje hasło wobec hasha. Implementacja w etapie 2 (auth)."""
    raise NotImplementedError("Weryfikacja haseł zostanie dodana w etapie 2 (auth)")


def create_access_token(subject: str) -> str:
    """Tworzy access token JWT dla podmiotu `subject`. Implementacja w etapie 2 (auth)."""
    raise NotImplementedError("Tworzenie tokenów JWT zostanie dodane w etapie 2 (auth)")


def create_refresh_token(subject: str) -> str:
    """Tworzy refresh token JWT dla podmiotu `subject`. Implementacja w etapie 2 (auth)."""
    raise NotImplementedError("Tworzenie tokenów JWT zostanie dodane w etapie 2 (auth)")


def decode_token(token: str) -> str:
    """Dekoduje token JWT i zwraca `subject`. Implementacja w etapie 2 (auth)."""
    raise NotImplementedError("Dekodowanie tokenów JWT zostanie dodane w etapie 2 (auth)")
