"""Tests for core.github_accounts — multi-account GitHub credential store."""

from core.github_accounts import GitHubAccountStore


class TestGitHubAccountStore:
    def setup_method(self, tmp_path_factory):
        pass

    def _store(self, tmp_path):
        return GitHubAccountStore(path=tmp_path / "github_accounts.json")

    def test_empty_store_returns_empty_list(self, tmp_path):
        store = self._store(tmp_path)
        assert store.list_accounts() == []

    def test_add_account_returns_masked_token(self, tmp_path):
        store = self._store(tmp_path)
        result = store.add_account("personal", "ghp_ABCDEFGHIJKLMNO1234", "alice")
        assert result["label"] == "personal"
        assert result["username"] == "alice"
        assert "ABCDEFGHIJKLMNO1234" not in result["masked_token"]
        assert "ghp_" in result["masked_token"] or result["masked_token"] == "****"

    def test_add_account_is_persisted(self, tmp_path):
        store = self._store(tmp_path)
        store.add_account("work", "ghp_WORKTOKEN123456789", "bob")

        # Re-load from disk
        store2 = GitHubAccountStore(path=tmp_path / "github_accounts.json")
        accounts = store2.list_accounts()
        assert len(accounts) == 1
        assert accounts[0]["label"] == "work"
        assert accounts[0]["username"] == "bob"

    def test_list_accounts_masks_tokens(self, tmp_path):
        store = self._store(tmp_path)
        store.add_account("personal", "ghp_XXXXXXXXXXXXXXXXXXX1", "alice")
        accounts = store.list_accounts()
        assert len(accounts) == 1
        assert "XXXXXXXXXXXXXXXXXXX1" not in accounts[0]["masked_token"]

    def test_get_token_returns_raw_token(self, tmp_path):
        store = self._store(tmp_path)
        token = "ghp_RAWTOKEN1234567890A"
        result = store.add_account("", token, "charlie")
        acct_id = result["id"]
        assert store.get_token(acct_id) == token

    def test_get_token_unknown_id_returns_empty(self, tmp_path):
        store = self._store(tmp_path)
        assert store.get_token("nonexistent") == ""

    def test_remove_account(self, tmp_path):
        store = self._store(tmp_path)
        result = store.add_account("to-remove", "ghp_REMOVETOKEN12345678", "dave")
        acct_id = result["id"]
        assert store.remove_account(acct_id) is True
        assert store.list_accounts() == []
        assert store.get_token(acct_id) == ""

    def test_remove_nonexistent_returns_false(self, tmp_path):
        store = self._store(tmp_path)
        assert store.remove_account("does-not-exist") is False

    def test_duplicate_token_updates_existing(self, tmp_path):
        store = self._store(tmp_path)
        token = "ghp_DUPLICATE1234567890A"
        store.add_account("first", token, "eve")
        store.add_account("second-label", token, "eve")
        # Only one account should exist
        accounts = store.list_accounts()
        assert len(accounts) == 1
        assert accounts[0]["label"] == "second-label"

    def test_multiple_accounts(self, tmp_path):
        store = self._store(tmp_path)
        store.add_account("personal", "ghp_PERSONAL1234567890A", "alice")
        store.add_account("work", "ghp_WORK123456789012345", "bob-org")
        accounts = store.list_accounts()
        assert len(accounts) == 2
        labels = {a["label"] for a in accounts}
        assert "personal" in labels
        assert "work" in labels

    def test_get_all_tokens_returns_all(self, tmp_path):
        store = self._store(tmp_path)
        tok1 = "ghp_TOKEN111111111111111"
        tok2 = "ghp_TOKEN222222222222222"
        store.add_account("a1", tok1, "u1")
        store.add_account("a2", tok2, "u2")
        all_tokens = store.get_all_tokens()
        assert len(all_tokens) == 2
        raw_tokens = {t for _, t in all_tokens}
        assert tok1 in raw_tokens
        assert tok2 in raw_tokens

    def test_label_defaults_to_username(self, tmp_path):
        store = self._store(tmp_path)
        result = store.add_account("", "ghp_LABELTEST1234567890", "frank")
        assert result["label"] == "frank"

    def test_label_defaults_to_id_if_no_username(self, tmp_path):
        store = self._store(tmp_path)
        result = store.add_account("", "ghp_NOLABEL1234567890123", "")
        # label should fall back to account id (non-empty)
        assert result["label"]

    def test_file_permissions_restrictive(self, tmp_path):
        import stat

        store = self._store(tmp_path)
        store.add_account("perm-test", "ghp_PERMTEST1234567890AB", "gary")
        path = tmp_path / "github_accounts.json"
        mode = stat.S_IMODE(path.stat().st_mode)
        # Owner read+write only (0o600)
        assert mode == stat.S_IRUSR | stat.S_IWUSR
