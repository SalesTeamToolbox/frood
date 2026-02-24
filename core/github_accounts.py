"""
Multi-account GitHub credential store.

Stores multiple GitHub Personal Access Tokens (PATs) under user-defined
labels in .agent42/github_accounts.json.  Each account has a stable UUID,
a human-readable label, the GitHub username (fetched at add time), and the
token itself.  Tokens are stored in plaintext — the file is chmod 600.
"""

import json
import logging
import stat
import threading
import uuid
from pathlib import Path

logger = logging.getLogger("agent42.github_accounts")

_DEFAULT_PATH = Path(".agent42") / "github_accounts.json"


class GitHubAccountStore:
    """Persist and retrieve multiple GitHub PAT accounts."""

    def __init__(self, path: Path | None = None):
        self._path = path or _DEFAULT_PATH
        self._accounts: dict[str, dict] = {}  # id -> {id, label, username, token}
        self._lock = threading.Lock()
        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for acct in data.get("accounts", []):
                if "id" in acct and "token" in acct:
                    self._accounts[acct["id"]] = acct
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load github accounts: %s", e)

    def _persist(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"accounts": list(self._accounts.values())}
        self._path.write_text(json.dumps(payload, indent=2))
        try:
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    # -- public API ------------------------------------------------------------

    def list_accounts(self) -> list[dict]:
        """Return all accounts with tokens masked."""
        result = []
        with self._lock:
            for acct in self._accounts.values():
                tok = acct.get("token", "")
                masked = tok[:4] + "..." + tok[-4:] if len(tok) > 8 else "****"
                result.append(
                    {
                        "id": acct["id"],
                        "label": acct.get("label", ""),
                        "username": acct.get("username", ""),
                        "masked_token": masked,
                    }
                )
        return result

    def add_account(self, label: str, token: str, username: str = "") -> dict:
        """Add or update an account.  Returns the stored record (token masked)."""
        account_id = uuid.uuid4().hex[:12]
        acct = {
            "id": account_id,
            "label": label.strip() or username or account_id,
            "username": username,
            "token": token,
        }
        with self._lock:
            # Prevent duplicate tokens
            for existing in self._accounts.values():
                if existing.get("token") == token:
                    existing["label"] = acct["label"]
                    existing["username"] = username or existing.get("username", "")
                    self._persist()
                    tok = token
                    masked = tok[:4] + "..." + tok[-4:] if len(tok) > 8 else "****"
                    return {
                        "id": existing["id"],
                        "label": existing["label"],
                        "username": existing["username"],
                        "masked_token": masked,
                    }
            self._accounts[account_id] = acct
            self._persist()
        tok = token
        masked = tok[:4] + "..." + tok[-4:] if len(tok) > 8 else "****"
        return {
            "id": account_id,
            "label": acct["label"],
            "username": username,
            "masked_token": masked,
        }

    def remove_account(self, account_id: str) -> bool:
        """Remove an account.  Returns True if it existed."""
        with self._lock:
            if account_id in self._accounts:
                del self._accounts[account_id]
                self._persist()
                return True
        return False

    def get_token(self, account_id: str) -> str:
        """Return the raw token for the given account id, or empty string."""
        with self._lock:
            return self._accounts.get(account_id, {}).get("token", "")

    def get_all_tokens(self) -> list[tuple[str, str]]:
        """Return list of (account_id, token) for all accounts."""
        with self._lock:
            return [(acct["id"], acct["token"]) for acct in self._accounts.values()]
