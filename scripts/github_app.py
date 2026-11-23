"""
GitHub App utilities for the Community PR API (M3c).

Provides the :class:`GitHubApp` client used by the dashboard to authenticate
as a GitHub App, obtain short-lived installation tokens, verify incoming
webhook signatures, and perform GitHub REST operations (create a pull request,
add labels, post a comment).

All credentials come from the vault via environment variables:

    VAULT_GITHUB_APP_PRIVATE_KEY   RSA PEM private key of the GitHub App
    VAULT_GITHUB_APP_ID            Numeric GitHub App identifier
    VAULT_GITHUB_WEBHOOK_SECRET    Secret used to verify webhook signatures

Installation tokens are cached in-memory with a 1-hour TTL and refreshed
lazily. Transient failures are retried with exponential backoff.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass

import httpx
from jose import jwt

logger = logging.getLogger("frood.github_app")

GITHUB_API_BASE = "https://api.github.com"

# A GitHub App JWT must expire within 10 minutes; we subtract 60s for clock skew.
_APP_JWT_TTL_SECONDS = 600
# Installation tokens typically live about an hour; cache them for 1 hour.
_INSTALLATION_TOKEN_TTL_SECONDS = 3600

# Maximum number of attempts for any single GitHub API call (1 initial + 3 retries).
_MAX_ATTEMPTS = 4

VAULT_PRIVATE_KEY_ENV = "VAULT_GITHUB_APP_PRIVATE_KEY"
VAULT_APP_ID_ENV = "VAULT_GITHUB_APP_ID"
VAULT_WEBHOOK_SECRET_ENV = "VAULT_GITHUB_WEBHOOK_SECRET"


class GitHubAppError(Exception):
    """Base error for GitHub App operations."""


class GitHubAppCredentialsError(GitHubAppError):
    """Raised when GitHub App credentials are missing or invalid."""


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # monotonic time after which the token is considered stale


class GitHubApp:
    """Client for GitHub App authentication and REST operations.

    Parameters are optional and fall back to the vault environment variables.
    ``http_client`` is injected mainly to make the class testable without
    hitting the network.
    """

    def __init__(
        self,
        app_id: str | None = None,
        private_key: str | None = None,
        webhook_secret: str | None = None,
        base_url: str = GITHUB_API_BASE,
        http_client: httpx.Client | None = None,
        token_ttl: float = _INSTALLATION_TOKEN_TTL_SECONDS,
    ):
        self.app_id = app_id or os.environ.get(VAULT_APP_ID_ENV, "")
        self.private_key = private_key or os.environ.get(VAULT_PRIVATE_KEY_ENV, "")
        self.webhook_secret = webhook_secret or os.environ.get(VAULT_WEBHOOK_SECRET_ENV, "")
        self.base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=30.0)
        self._token_ttl = token_ttl
        self._cache: dict[str, _CachedToken] = {}
        self._validate_credentials()

    # -- credentials ---------------------------------------------------------

    def _validate_credentials(self) -> None:
        if not self.app_id:
            raise GitHubAppCredentialsError(
                f"GitHub App ID not configured (set {VAULT_APP_ID_ENV})"
            )
        if not self.private_key:
            raise GitHubAppCredentialsError(
                f"GitHub App private key not configured (set {VAULT_PRIVATE_KEY_ENV})"
            )

    @property
    def configured(self) -> bool:
        """True when both the app ID and private key are present."""
        return bool(self.app_id and self.private_key)

    # -- JWT used to authenticate as the GitHub App itself ------------------

    def _app_jwt(self) -> str:
        """Build a short-lived JWT to authenticate as the GitHub App."""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # allow for clock skew
            "exp": now + _APP_JWT_TTL_SECONDS,
            "iss": int(self.app_id),
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    # -- installation token (cached, TTL 1 hour) -----------------------------

    def get_installation_token(self, installation_id: int | str) -> str:
        """Return a short-lived installation access token.

        A cached token is returned while still valid; otherwise a fresh token
        is requested from GitHub and cached for ``token_ttl`` seconds.
        """
        key = str(installation_id)
        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and now < cached.expires_at:
            return cached.token

        token = self._fetch_installation_token(installation_id)
        self._cache[key] = _CachedToken(
            token=token,
            expires_at=now + self._token_ttl,
        )
        return token

    def _fetch_installation_token(self, installation_id: int | str) -> str:
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {self._app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2024-11-28",
            "User-Agent": "frood-github-app",
        }
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = self._http.post(url, headers=headers)
                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise GitHubAppError(
                            f"Installation token response was not valid JSON: {exc}"
                        ) from exc
                    token = data.get("token")
                    if not token:
                        raise GitHubAppError("Installation token response missing 'token' field")
                    return token
                # Authentication problems are permanent — do not retry.
                if resp.status_code in (401, 403):
                    raise GitHubAppError(
                        f"GitHub rejected installation token request "
                        f"({resp.status_code}): {resp.text[:200]}"
                    )
                # Retry on rate limiting / transient server errors.
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = GitHubAppError(
                        f"GitHub API {resp.status_code} fetching installation token"
                    )
                    self._sleep_backoff(attempt)
                    continue
                raise GitHubAppError(
                    f"GitHub API {resp.status_code} fetching installation token: {resp.text[:300]}"
                )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = exc
                self._sleep_backoff(attempt)
        raise GitHubAppError(
            f"Failed to fetch installation token after {_MAX_ATTEMPTS} attempts: {last_error}"
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(2**attempt, 8))

    # -- webhook signature verification -------------------------------------

    @staticmethod
    def verify_webhook_signature(
        payload: bytes,
        signature: str | None,
        webhook_secret: str | None,
    ) -> bool:
        """Constant-time HMAC-SHA256 verification of a GitHub webhook signature.

        ``signature`` is the ``X-Hub-Signature-256`` header value
        (``sha256=<hex>``). Returns ``True`` only when the digest matches.
        Any missing or malformed input returns ``False``.
        """
        if not signature or not webhook_secret:
            return False
        try:
            algo, _, hex_digest = signature.partition("=")
            if algo.lower() != "sha256" or not hex_digest:
                return False
            expected = hmac.new(webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, hex_digest)
        except (ValueError, AttributeError, TypeError):
            return False

    # -- REST helpers --------------------------------------------------------

    def _installation_headers(self, installation_id: int | str) -> dict:
        token = self.get_installation_token(installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2024-11-28",
            "User-Agent": "frood-github-app",
        }

    @staticmethod
    def _repo_path(repo_full_name: str) -> str:
        return f"repos/{repo_full_name}"

    @staticmethod
    def validate_repo_full_name(repo_full_name: str) -> tuple[str, str]:
        """Split ``owner/repo`` into its two parts, raising on malformed input."""
        parts = (repo_full_name or "").strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise GitHubAppError(
                f"Invalid repo_full_name '{repo_full_name}'; expected 'owner/repo'"
            )
        return parts[0], parts[1]

    def _request_with_retry(self, method: str, url: str, headers: dict, **kwargs):
        """Perform a GitHub API request with retry on transient failures.

        Client errors (401/403/404/422) are not retried. Returns the response
        object on success; raises :class:`GitHubAppError` after retries exhaust.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = self._http.request(method, url, headers=headers, **kwargs)
                if 200 <= resp.status_code < 300:
                    return resp
                if resp.status_code in (401, 403, 404, 422):
                    raise GitHubAppError(
                        f"GitHub API {resp.status_code} for {method} {url}: {resp.text[:300]}"
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = GitHubAppError(f"GitHub API {resp.status_code}")
                    self._sleep_backoff(attempt)
                    continue
                raise GitHubAppError(
                    f"GitHub API {resp.status_code} for {method} {url}: {resp.text[:300]}"
                )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = exc
                self._sleep_backoff(attempt)
        raise GitHubAppError(f"GitHub request failed after {_MAX_ATTEMPTS} attempts: {last_error}")

    def workflow_dispatch(
        self,
        installation_id: int | str,
        repo_full_name: str,
        workflow_id: str,
        ref: str = "main",
        inputs: dict | None = None,
    ) -> dict:
        """Trigger a GitHub Actions workflow dispatch. Returns the parsed JSON.

        Best-effort: callers treat failures as non-fatal (CI re-run is a hint,
        not a blocking requirement).
        """
        self.validate_repo_full_name(repo_full_name)
        url = (
            f"{self.base_url}/{self._repo_path(repo_full_name)}"
            f"/actions/workflows/{workflow_id}/dispatches"
        )
        headers = self._installation_headers(installation_id)
        payload: dict = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        resp = self._request_with_retry("POST", url, headers, json=payload)
        try:
            return resp.json()
        except ValueError:
            return {"status": resp.status_code}

    def create_pr(
        self,
        installation_id: int | str,
        repo_full_name: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict:
        """Create a pull request via a GitHub App installation token.

        Returns the parsed JSON response, which includes ``number``, ``html_url``
        and ``url``.
        """
        self.validate_repo_full_name(repo_full_name)
        url = f"{self.base_url}/{self._repo_path(repo_full_name)}/pulls"
        headers = self._installation_headers(installation_id)
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
        }
        resp = self._request_with_retry("POST", url, headers, json=payload)
        try:
            return resp.json()
        except ValueError as exc:
            raise GitHubAppError(f"Create PR response was not valid JSON: {exc}") from exc

    def add_labels(
        self,
        installation_id: int | str,
        repo_full_name: str,
        pr_number: int,
        labels: list[str],
    ) -> list[str]:
        """Add labels to a pull request (treated as an issue).

        Returns the list of added label names.
        """
        self.validate_repo_full_name(repo_full_name)
        url = f"{self.base_url}/{self._repo_path(repo_full_name)}/issues/{pr_number}/labels"
        headers = self._installation_headers(installation_id)
        resp = self._request_with_retry("POST", url, headers, json=labels)
        try:
            return [label.get("name") for label in resp.json()]
        except ValueError as exc:
            raise GitHubAppError(f"Add labels response was not valid JSON: {exc}") from exc

    def post_comment(
        self,
        installation_id: int | str,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> dict:
        """Post a comment on a pull request. Returns the parsed comment JSON."""
        self.validate_repo_full_name(repo_full_name)
        url = f"{self.base_url}/{self._repo_path(repo_full_name)}/issues/{pr_number}/comments"
        headers = self._installation_headers(installation_id)
        resp = self._request_with_retry("POST", url, headers, json={"body": body})
        try:
            return resp.json()
        except ValueError as exc:
            raise GitHubAppError(f"Post comment response was not valid JSON: {exc}") from exc

    def close(self) -> None:
        """Close the underlying HTTP client."""
        try:
            self._http.close()
        except Exception:
            pass
