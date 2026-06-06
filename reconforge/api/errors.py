"""Structured API errors for the local REST API foundation."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(ValueError):
    """Raised for safe, structured API responses."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def request_id(request: Request) -> str:
    """Return the per-request id assigned by middleware."""

    value = getattr(request.state, "request_id", "")
    return str(value) if value else uuid.uuid4().hex


def error_payload(*, code: str, message: str, request_id_value: str) -> dict[str, dict[str, str]]:
    """Build a structured JSON error payload."""

    return {"error": {"code": code, "message": message, "request_id": request_id_value}}


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle safe API errors."""

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code=exc.code, message=exc.message, request_id_value=request_id(request)),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette/FastAPI HTTP errors without leaking internals."""

    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code="http_error", message=detail, request_id_value=request_id(request)),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors without echoing sensitive submitted values."""

    return JSONResponse(
        status_code=422,
        content=error_payload(code="validation_error", message="Request validation failed.", request_id_value=request_id(request)),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with a sanitized message."""

    return JSONResponse(
        status_code=500,
        content=error_payload(code="internal_error", message="Internal API error.", request_id_value=request_id(request)),
    )


def safe_model_dump(value: Any) -> Any:
    """Return Pydantic-compatible JSON values."""

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
