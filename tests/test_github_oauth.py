"""Tests for GitHub OAuth device flow (all HTTP calls mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.github_oauth import GitHubDeviceAuth


class TestGitHubDeviceAuth:
    """Test GitHub OAuth device flow."""

    def setup_method(self):
        self.auth = GitHubDeviceAuth(client_id="test-client-id")

    @pytest.mark.asyncio
    async def test_start_device_flow_no_client_id(self):
        auth = GitHubDeviceAuth(client_id="")
        with pytest.raises(ValueError, match="GITHUB_CLIENT_ID"):
            await auth.start_device_flow()

    @pytest.mark.asyncio
    async def test_start_device_flow(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "device_code": "dc_test123",
            "expires_in": 900,
            "interval": 5,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await self.auth.start_device_flow()

            assert result["user_code"] == "ABCD-1234"
            assert result["verification_uri"] == "https://github.com/login/device"
            assert result["device_code"] == "dc_test123"

    @pytest.mark.asyncio
    async def test_poll_for_token_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "gho_testtoken123"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await self.auth.poll_for_token("dc_test123")
            assert token == "gho_testtoken123"

    @pytest.mark.asyncio
    async def test_poll_for_token_pending(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "authorization_pending"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await self.auth.poll_for_token("dc_test123")
            assert token is None

    @pytest.mark.asyncio
    async def test_poll_for_token_expired(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "expired_token"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(TimeoutError):
                await self.auth.poll_for_token("dc_test123")

    @pytest.mark.asyncio
    async def test_poll_for_token_denied(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "access_denied"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(PermissionError):
                await self.auth.poll_for_token("dc_test123")

    @pytest.mark.asyncio
    async def test_create_repo(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "full_name": "user/my-repo",
            "html_url": "https://github.com/user/my-repo",
            "clone_url": "https://github.com/user/my-repo.git",
            "ssh_url": "git@github.com:user/my-repo.git",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await GitHubDeviceAuth.create_repo(
                token="gho_test", name="my-repo", private=True
            )
            assert result["full_name"] == "user/my-repo"
            assert result["html_url"] == "https://github.com/user/my-repo"

    @pytest.mark.asyncio
    async def test_get_user(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "avatar_url": "https://avatars.githubusercontent.com/u/123",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("core.github_oauth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await GitHubDeviceAuth.get_user("gho_test")
            assert result["login"] == "testuser"

    def test_save_token(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("OTHER_VAR=value\n")

        GitHubDeviceAuth.save_token("gho_newtoken", env_path)

        content = env_path.read_text()
        assert "GITHUB_OAUTH_TOKEN=gho_newtoken" in content
        assert "OTHER_VAR=value" in content

    def test_save_token_overwrites_existing(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("GITHUB_OAUTH_TOKEN=old_token\nOTHER=val\n")

        GitHubDeviceAuth.save_token("gho_newtoken", env_path)

        content = env_path.read_text()
        assert "GITHUB_OAUTH_TOKEN=gho_newtoken" in content
        assert "old_token" not in content
