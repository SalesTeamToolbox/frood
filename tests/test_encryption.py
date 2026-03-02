"""Tests for core.encryption — Fernet symmetric encryption utility."""


class TestEncryption:
    """Test encrypt/decrypt roundtrip, legacy passthrough, and error cases."""

    def test_roundtrip(self):
        from core.encryption import decrypt_value, encrypt_value

        secret = "test-secret-key-at-least-32-chars-long"
        plaintext = "ghp_abc123secrettoken"
        encrypted = encrypt_value(plaintext, secret)
        assert encrypted != plaintext
        assert encrypted.startswith("fernet:1:")
        assert decrypt_value(encrypted, secret) == plaintext

    def test_legacy_plaintext_passthrough(self):
        from core.encryption import decrypt_value

        legacy = "ghp_plaintext_token_no_prefix"
        assert decrypt_value(legacy, "any-secret") == legacy

    def test_is_encrypted(self):
        from core.encryption import encrypt_value, is_encrypted

        assert not is_encrypted("plain-value")
        assert not is_encrypted("")
        encrypted = encrypt_value("hello", "secret123")
        assert is_encrypted(encrypted)

    def test_empty_secret_returns_plaintext(self):
        from core.encryption import decrypt_value, encrypt_value

        plaintext = "my-token"
        assert encrypt_value(plaintext, "") == plaintext
        assert decrypt_value("fernet:1:junk", "") == "fernet:1:junk"

    def test_wrong_secret_returns_raw(self):
        from core.encryption import decrypt_value, encrypt_value

        secret1 = "correct-secret-key-32-chars-long"
        secret2 = "wrong-secret-key-also-32-chars!!"
        encrypted = encrypt_value("sensitive", secret1)
        # Wrong secret should return raw value (logged error, no crash)
        result = decrypt_value(encrypted, secret2)
        assert result == encrypted  # returns the raw encrypted string

    def test_multiple_values_same_secret(self):
        from core.encryption import decrypt_value, encrypt_value

        secret = "shared-secret-key-32-chars-long!"
        values = ["token-a", "token-b", "token-c"]
        encrypted = [encrypt_value(v, secret) for v in values]
        # All should be different ciphertexts
        assert len(set(encrypted)) == 3
        # All should decrypt correctly
        for enc, orig in zip(encrypted, values):
            assert decrypt_value(enc, secret) == orig


class TestEncryptionMissingCryptography:
    """Test graceful degradation when cryptography is not available."""

    def test_encrypt_without_cryptography(self, monkeypatch):
        """Simulate missing cryptography by clearing the Fernet cache."""
        from core.encryption import _get_fernet

        # Clear cache so we can monkeypatch
        _get_fernet.cache_clear()

        import core.encryption as enc_mod

        original_get_fernet = enc_mod._get_fernet

        def mock_get_fernet(secret):
            return None

        monkeypatch.setattr(enc_mod, "_get_fernet", mock_get_fernet)
        result = enc_mod.encrypt_value("plaintext", "secret")
        assert result == "plaintext"

        # Restore
        monkeypatch.setattr(enc_mod, "_get_fernet", original_get_fernet)
        _get_fernet.cache_clear()
