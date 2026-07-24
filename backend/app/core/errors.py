"""Wyjątki domenowe.

Warstwa `service` (i wyjątkowo `repository`) rzuca wyłącznie te klasy,
nigdy `fastapi.HTTPException` — mapowanie na odpowiedź HTTP siedzi w jednym
miejscu: `exception_handler` w `app.main` (patrz docs/api-kontrakt.md,
sekcja „Błędy").
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Bazowa klasa błędów domenowych.

    Podklasy ustawiają `code` (identyfikator błędu widoczny w odpowiedzi
    JSON) i `status_code` (kod HTTP, zgodnie z tabelą w
    docs/api-kontrakt.md).
    """

    code: str = "domain_error"
    status_code: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    """Zasób nie istnieje lub należy do innego użytkownika (404, konsekwentnie —
    nigdy 403, żeby nie zdradzać istnienia cudzego zasobu, patrz skill
    `izolacja-danych`).
    """

    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    """Konflikt stanu domenowego, np. pozycja dla tego aktywa już istnieje (409)."""

    code = "conflict"
    status_code = 409


class ValidationError(DomainError):
    """Błąd walidacji domenowej, poza tym co łapie już Pydantic (422)."""

    code = "validation_error"
    status_code = 422


class ProviderUnavailableError(DomainError):
    """Dostawca danych rynkowych niedostępny — dane mogą być nieświeże (503)."""

    code = "provider_unavailable"
    status_code = 503
