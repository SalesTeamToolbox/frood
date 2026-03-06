"""Unified error taxonomy and classification utilities.

Exposes backend error classifiers (from iteration_engine) as structured
error codes with user-friendly messages and actionable guidance.
"""

from enum import Enum


class ErrorCode(Enum):
    """Canonical error codes returned in API responses."""

    AUTH_EXPIRED = "auth_expired"
    AUTH_INVALID = "auth_invalid"
    RATE_LIMITED = "rate_limited"
    PAYMENT_REQUIRED = "payment_required"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    SERVICE_UNAVAILABLE = "service_unavailable"
    UNKNOWN = "unknown"


# User-friendly messages and actionable guidance for each error code.
ERROR_MESSAGES: dict[ErrorCode, dict[str, str]] = {
    ErrorCode.AUTH_EXPIRED: {
        "message": "Your session has expired.",
        "action": "Please log in again to continue.",
    },
    ErrorCode.AUTH_INVALID: {
        "message": "Invalid credentials.",
        "action": "Check your username and password and try again.",
    },
    ErrorCode.RATE_LIMITED: {
        "message": "Too many requests.",
        "action": "Wait a moment and try again.",
    },
    ErrorCode.PAYMENT_REQUIRED: {
        "message": "API credits exhausted.",
        "action": "Add more credits or wait for daily reset.",
    },
    ErrorCode.NETWORK_ERROR: {
        "message": "Network connection failed.",
        "action": "Check your internet connection and try again.",
    },
    ErrorCode.TIMEOUT: {
        "message": "Request took too long.",
        "action": "Try again or simplify the request.",
    },
    ErrorCode.VALIDATION_ERROR: {
        "message": "Invalid input.",
        "action": "Check the form fields and try again.",
    },
    ErrorCode.NOT_FOUND: {
        "message": "Resource not found.",
        "action": "The item may have been deleted or the URL is incorrect.",
    },
    ErrorCode.FORBIDDEN: {
        "message": "Access denied.",
        "action": "You do not have permission for this action.",
    },
    ErrorCode.SERVICE_UNAVAILABLE: {
        "message": "Service temporarily unavailable.",
        "action": "The server is busy. Please try again shortly.",
    },
    ErrorCode.UNKNOWN: {
        "message": "An unexpected error occurred.",
        "action": "Try again. If the problem persists, check the server logs.",
    },
}


def classify_error(exception: Exception) -> ErrorCode:
    """Map an exception to an ErrorCode.

    Uses the same heuristics as iteration_engine._is_auth_error(),
    _is_rate_limited(), and _is_payment_error() to classify errors
    consistently across the backend.
    """
    msg = str(exception).lower()

    # Auth errors (401, unauthorized, invalid key)
    if (
        "401" in msg
        or "unauthorized" in msg
        or "invalid api key" in msg
        or "authentication" in msg
    ):
        return ErrorCode.AUTH_EXPIRED

    # Forbidden (403)
    if "forbidden" in msg and "403" in msg:
        return ErrorCode.FORBIDDEN

    # Rate limiting (429, quota exhausted)
    if (
        "429" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
    ):
        return ErrorCode.RATE_LIMITED

    # Payment required (402, spend limit)
    if (
        "402" in msg
        or "spend limit" in msg
        or "spending limit" in msg
        or "payment required" in msg
    ):
        return ErrorCode.PAYMENT_REQUIRED

    # Timeout
    if "timeout" in msg or "timed out" in msg:
        return ErrorCode.TIMEOUT

    # Not found (404)
    if "404" in msg or "not found" in msg:
        return ErrorCode.NOT_FOUND

    # Network errors
    if (
        "connection" in msg
        or "network" in msg
        or "dns" in msg
        or "refused" in msg
    ):
        return ErrorCode.NETWORK_ERROR

    # Validation
    if "validation" in msg or "invalid" in msg or "required" in msg:
        return ErrorCode.VALIDATION_ERROR

    # Service unavailable (503)
    if "503" in msg or "unavailable" in msg or "overloaded" in msg:
        return ErrorCode.SERVICE_UNAVAILABLE

    return ErrorCode.UNKNOWN


def get_error_response(exception: Exception) -> dict:
    """Build a structured error response dict from an exception.

    Returns a dict with keys: error, message, action — suitable for
    returning directly from a FastAPI endpoint.
    """
    code = classify_error(exception)
    info = ERROR_MESSAGES.get(code, ERROR_MESSAGES[ErrorCode.UNKNOWN])
    return {
        "error": code.value,
        "message": info["message"],
        "action": info["action"],
    }


def get_http_error_response(status_code: int, detail: str = "") -> dict:
    """Build a structured error response from an HTTP status code and detail.

    Used by the global exception handler for HTTPException instances.
    """
    code = _status_to_error_code(status_code, detail)
    info = ERROR_MESSAGES.get(code, ERROR_MESSAGES[ErrorCode.UNKNOWN])
    # Use the original detail as the message if available, otherwise fallback
    message = detail if detail else info["message"]
    return {
        "error": code.value,
        "message": message,
        "action": info["action"],
    }


def _status_to_error_code(status_code: int, detail: str = "") -> ErrorCode:
    """Map an HTTP status code to an ErrorCode."""
    detail_lower = detail.lower() if detail else ""

    if status_code == 401:
        if "expired" in detail_lower or "session" in detail_lower:
            return ErrorCode.AUTH_EXPIRED
        return ErrorCode.AUTH_INVALID
    if status_code == 403:
        return ErrorCode.FORBIDDEN
    if status_code == 404:
        return ErrorCode.NOT_FOUND
    if status_code == 422:
        return ErrorCode.VALIDATION_ERROR
    if status_code == 429:
        return ErrorCode.RATE_LIMITED
    if status_code == 402:
        return ErrorCode.PAYMENT_REQUIRED
    if status_code == 408:
        return ErrorCode.TIMEOUT
    if status_code == 503:
        return ErrorCode.SERVICE_UNAVAILABLE

    # Check detail text for additional classification hints
    if detail_lower:
        return classify_error(Exception(detail))

    return ErrorCode.UNKNOWN
