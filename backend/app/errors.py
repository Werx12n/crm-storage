"""Доменні помилки → HTTP-відповіді з повідомленням українською."""
from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str, code: str = "error", status_code: int | None = None, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        if status_code:
            self.status_code = status_code
        self.extra = extra


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class Forbidden(DomainError):
    status_code = 403


class Invalid(DomainError):
    status_code = 422


async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code, **exc.extra},
    )
