"""Tests for error handling: error codes, classification, and API responses."""

import pytest

from core.error_codes import (
    ErrorCode,
    ERROR_MESSAGES,
    classify_error,
    get_error_response,
    get_http_error_response,
    _status_to_error_code,
)


class TestErrorCodeEnum:
    """Verify ErrorCode enum values and completeness."""

    def test_all_codes_have_messages(self):
        """Every ErrorCode must have an entry in ERROR_MESSAGES."""
        for code in ErrorCode:
            assert code in ERROR_MESSAGES, f"Missing ERROR_MESSAGES entry for {code}"

    def test_all_messages_have_required_keys(self):
        """Every ERROR_MESSAGES entry must have 'message' and 'action' keys."""
        for code, info in ERROR_MESSAGES.items():
            assert "message" in info, f"Missing 'message' key for {code}"
            assert "action" in info, f"Missing 'action' key for {code}"
            assert isinstance(info["message"], str)
            assert isinstance(info["action"], str)
            assert len(info["message"]) > 0
            assert len(info["action"]) > 0

    def test_error_code_values_are_snake_case(self):
        """Error code values should be lowercase snake_case strings."""
        for code in ErrorCode:
            assert code.value == code.value.lower()
            assert " " not in code.value


class TestClassifyError:
    """Test exception-to-ErrorCode classification."""

    def test_auth_error_401(self):
        err = Exception("Error code: 401 - Unauthorized")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED

    def test_auth_error_unauthorized(self):
        err = Exception("unauthorized access to endpoint")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED

    def test_auth_error_invalid_api_key(self):
        err = Exception("Invalid API key provided")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED

    def test_auth_error_authentication(self):
        err = Exception("Authentication failed for user")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED

    def test_forbidden_error(self):
        err = Exception("403 Forbidden - access denied")
        assert classify_error(err) == ErrorCode.FORBIDDEN

    def test_rate_limit_429(self):
        err = Exception("Error code: 429 - Too Many Requests")
        assert classify_error(err) == ErrorCode.RATE_LIMITED

    def test_rate_limit_text(self):
        err = Exception("Rate limit exceeded, try again later")
        assert classify_error(err) == ErrorCode.RATE_LIMITED

    def test_rate_limit_underscore(self):
        err = Exception("rate_limit_exceeded")
        assert classify_error(err) == ErrorCode.RATE_LIMITED

    def test_rate_limit_resource_exhausted(self):
        err = Exception("RESOURCE_EXHAUSTED: quota depleted")
        assert classify_error(err) == ErrorCode.RATE_LIMITED

    def test_rate_limit_quota(self):
        err = Exception("Quota exceeded for this API key")
        assert classify_error(err) == ErrorCode.RATE_LIMITED

    def test_payment_error_402(self):
        err = Exception("Error code: 402 - Payment Required")
        assert classify_error(err) == ErrorCode.PAYMENT_REQUIRED

    def test_payment_error_spend_limit(self):
        err = Exception("API key USD spend limit exceeded")
        assert classify_error(err) == ErrorCode.PAYMENT_REQUIRED

    def test_payment_error_spending_limit(self):
        err = Exception("spending limit reached for this key")
        assert classify_error(err) == ErrorCode.PAYMENT_REQUIRED

    def test_payment_required_text(self):
        err = Exception("Payment required: insufficient credits")
        assert classify_error(err) == ErrorCode.PAYMENT_REQUIRED

    def test_timeout_error(self):
        err = Exception("Request timeout after 30s")
        assert classify_error(err) == ErrorCode.TIMEOUT

    def test_timed_out_error(self):
        err = Exception("Connection timed out")
        assert classify_error(err) == ErrorCode.TIMEOUT

    def test_not_found_404(self):
        err = Exception("404 Not Found")
        assert classify_error(err) == ErrorCode.NOT_FOUND

    def test_not_found_text(self):
        err = Exception("Resource not found")
        assert classify_error(err) == ErrorCode.NOT_FOUND

    def test_network_connection_error(self):
        err = Exception("Connection refused by server")
        assert classify_error(err) == ErrorCode.NETWORK_ERROR

    def test_network_dns_error(self):
        err = Exception("DNS resolution failed")
        assert classify_error(err) == ErrorCode.NETWORK_ERROR

    def test_validation_error(self):
        err = Exception("Validation error: field 'name' is required")
        assert classify_error(err) == ErrorCode.VALIDATION_ERROR

    def test_service_unavailable_503(self):
        err = Exception("503 Service Unavailable")
        assert classify_error(err) == ErrorCode.SERVICE_UNAVAILABLE

    def test_service_overloaded(self):
        err = Exception("Server overloaded, try later")
        assert classify_error(err) == ErrorCode.SERVICE_UNAVAILABLE

    def test_unknown_error_fallback(self):
        err = Exception("Something completely unexpected happened")
        assert classify_error(err) == ErrorCode.UNKNOWN

    def test_empty_error_message(self):
        err = Exception("")
        assert classify_error(err) == ErrorCode.UNKNOWN

    def test_classification_is_case_insensitive(self):
        err = Exception("UNAUTHORIZED ACCESS")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED

    def test_classification_priority_auth_over_not_found(self):
        """When message contains both '401' and 'not found', auth wins."""
        err = Exception("401 endpoint not found")
        assert classify_error(err) == ErrorCode.AUTH_EXPIRED


class TestGetErrorResponse:
    """Test the get_error_response() helper."""

    def test_returns_structured_dict(self):
        err = Exception("429 rate limited")
        result = get_error_response(err)
        assert "error" in result
        assert "message" in result
        assert "action" in result

    def test_rate_limit_response(self):
        err = Exception("Rate limit exceeded")
        result = get_error_response(err)
        assert result["error"] == "rate_limited"
        assert "Too many requests" in result["message"]
        assert "Wait" in result["action"]

    def test_unknown_error_response(self):
        err = Exception("wibble wobble")
        result = get_error_response(err)
        assert result["error"] == "unknown"
        assert "unexpected" in result["message"]


class TestGetHttpErrorResponse:
    """Test the get_http_error_response() helper for HTTPException handling."""

    def test_401_returns_auth_invalid(self):
        result = get_http_error_response(401, "Bad credentials")
        assert result["error"] == "auth_invalid"

    def test_401_expired_returns_auth_expired(self):
        result = get_http_error_response(401, "Token expired or invalid session")
        assert result["error"] == "auth_expired"

    def test_403_returns_forbidden(self):
        result = get_http_error_response(403, "Admin access required")
        assert result["error"] == "forbidden"
        assert result["message"] == "Admin access required"

    def test_404_returns_not_found(self):
        result = get_http_error_response(404, "Task not found")
        assert result["error"] == "not_found"
        assert result["message"] == "Task not found"

    def test_422_returns_validation_error(self):
        result = get_http_error_response(422)
        assert result["error"] == "validation_error"

    def test_429_returns_rate_limited(self):
        result = get_http_error_response(429, "Too many login attempts")
        assert result["error"] == "rate_limited"
        assert result["message"] == "Too many login attempts"
        assert "Wait" in result["action"]

    def test_402_returns_payment_required(self):
        result = get_http_error_response(402)
        assert result["error"] == "payment_required"

    def test_408_returns_timeout(self):
        result = get_http_error_response(408, "Request timed out")
        assert result["error"] == "timeout"

    def test_503_returns_service_unavailable(self):
        result = get_http_error_response(503)
        assert result["error"] == "service_unavailable"

    def test_500_with_detail_classifies_from_text(self):
        result = get_http_error_response(500, "Connection refused to database")
        assert result["error"] == "network_error"

    def test_500_without_detail_returns_unknown(self):
        result = get_http_error_response(500)
        assert result["error"] == "unknown"

    def test_preserves_detail_as_message(self):
        result = get_http_error_response(404, "The task you requested was not found")
        assert result["message"] == "The task you requested was not found"

    def test_uses_default_message_when_no_detail(self):
        result = get_http_error_response(429)
        assert "Too many requests" in result["message"]

    def test_action_always_present(self):
        """Every response must have a non-empty action string."""
        for status in [400, 401, 403, 404, 408, 422, 429, 500, 503]:
            result = get_http_error_response(status)
            assert isinstance(result["action"], str)
            assert len(result["action"]) > 0


class TestStatusToErrorCode:
    """Test the internal _status_to_error_code mapping."""

    def test_maps_all_known_codes(self):
        known = {
            401: ErrorCode.AUTH_INVALID,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            422: ErrorCode.VALIDATION_ERROR,
            429: ErrorCode.RATE_LIMITED,
            402: ErrorCode.PAYMENT_REQUIRED,
            408: ErrorCode.TIMEOUT,
            503: ErrorCode.SERVICE_UNAVAILABLE,
        }
        for status, expected in known.items():
            assert _status_to_error_code(status) == expected, f"Failed for status {status}"

    def test_unknown_status_returns_unknown(self):
        assert _status_to_error_code(418) == ErrorCode.UNKNOWN

    def test_401_with_expired_keyword(self):
        assert _status_to_error_code(401, "Token expired") == ErrorCode.AUTH_EXPIRED

    def test_401_with_session_keyword(self):
        assert _status_to_error_code(401, "Invalid session") == ErrorCode.AUTH_EXPIRED
