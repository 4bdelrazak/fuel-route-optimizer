"""Render every failure as `{"error": {"code", "message"}}`.

Clients get a stable machine-readable code and a sentence they can show a user.
Nothing from an external service's response body and no stack trace ever reaches
them.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.errors import ApiError

logger = logging.getLogger(__name__)


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, ApiError):
        return _error(exc.code, exc.message, exc.status_code)

    if isinstance(exc, ValidationError):
        return _error(
            "INVALID_INPUT",
            "The request body is invalid.",
            status.HTTP_400_BAD_REQUEST,
            details=exc.detail,
        )

    if isinstance(exc, APIException):
        return _error(
            getattr(exc, "default_code", "REQUEST_FAILED").upper(),
            str(exc.detail),
            exc.status_code,
        )

    # Anything else is a bug. Log it with the traceback and let DRF fall through
    # to a bodyless 500 rather than describing our internals to the caller.
    logger.exception("Unhandled exception in %s", context.get("view"))
    return drf_exception_handler(exc, context)


def _error(code: str, message: str, status_code: int, details=None) -> Response:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["fields"] = details  # type: ignore[index]
    return Response(body, status=status_code)
