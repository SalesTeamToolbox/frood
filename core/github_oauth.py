"""
GitHub OAuth device flow for repository creation.

Uses GitHub's device authorization grant so users can authenticate
via browser without exposing tokens in the dashboard. The flow:

1. Backend requests a device code from GitHub
2. Frontend shows the user_code and verification_uri
3. User opens the URI in browser and enters the code
4. Backend polls GitHub until the user authorizes
5. Token is stored in .env for future use

Requires a GitHub OAuth App with device flow enabled.
"""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger("agent42.github_oauth")

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"


class GitHubDeviceAuth:
    """GitHub OAuth device flow for headless authentication."""

    def __init__(self, client_id: str):
        self._client_id = client_id

    async def start_device_flow(self) -> dict:
        """Start the device authorization flow.

        Returns dict with: user_code, verification_uri, device_code,
        expires_in, interval.
        """
        if not self._client_id:
            raise ValueError("GITHUB_CLIENT_ID not configured")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GITHUB_DEVICE_CODE_URL,
                data={
                    "client_id": self._client_id,
                    "scope": "repo",
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "user_code": data["user_code"],
                "verification_uri": data["verification_uri"],
                "device_code": data["device_code"],
                "expires_in": data.get("expires_in", 900),
                "interval": data.get("interval", 5),
            }

    async def poll_for_token(self, device_code: str) -> str | None:
        """Poll GitHub for access token (single attempt).

        Returns the access_token if authorized, None if still pending,
        raises on error/expiry.
        """
        if not self._client_id:
            raise ValueError("GITHUB_CLIENT_ID not configured")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if "access_token" in data:
                return data["access_token"]

            error = data.get("error", "")
            if error == "authorization_pending":
                return None  # User hasn't authorized yet
            if error == "slow_down":
                return None  # Need to slow down polling
            if error == "expired_token":
                raise TimeoutError("Device code expired. Please restart the flow.")
            if error == "access_denied":
                raise PermissionError("User denied the authorization request.")

            raise RuntimeError(f"GitHub OAuth error: {error}")

    @staticmethod
    async def create_repo(
        token: str,
        name: str,
        private: bool = True,
        description: str = "",
    ) -> dict:
        """Create a GitHub repository using the authenticated token.

        Returns dict with: full_name, html_url, clone_url, ssh_url.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GITHUB_API_URL}/user/repos",
                json={
                    "name": name,
                    "description": description,
                    "private": private,
                    "auto_init": True,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "full_name": data["full_name"],
                "html_url": data["html_url"],
                "clone_url": data["clone_url"],
                "ssh_url": data["ssh_url"],
            }

    @staticmethod
    async def get_user(token: str) -> dict:
        """Get the authenticated GitHub user info."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API_URL}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "login": data["login"],
                "name": data.get("name", ""),
                "avatar_url": data.get("avatar_url", ""),
            }

    @staticmethod
    def save_token(token: str, env_path: Path):
        """Save the OAuth token to .env file."""
        lines: list[str] = []
        found = False
        if env_path.exists():
            lines = env_path.read_text().splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("GITHUB_OAUTH_TOKEN=") or line.strip().startswith(
                    "# GITHUB_OAUTH_TOKEN="
                ):
                    lines[i] = f"GITHUB_OAUTH_TOKEN={token}"
                    found = True
                    break
        if not found:
            lines.append(f"GITHUB_OAUTH_TOKEN={token}")
        env_path.write_text("\n".join(lines) + "\n")
        logger.info("GitHub OAuth token saved to .env")
