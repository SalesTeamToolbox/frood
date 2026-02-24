"""
Device authentication for multi-device gateway access.

Devices (Apple Watch, laptop, phone, tablet) register with Agent42 and receive
persistent API keys. Keys are stored as SHA-256 hashes in a JSONL file;
the raw key is returned only once at registration.

API keys use the ``ak_`` prefix so the auth layer can distinguish them from
JWT tokens at a glance.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.device_auth")

VALID_DEVICE_TYPES = {"laptop", "watch", "phone", "tablet", "desktop", "other"}
VALID_CAPABILITIES = {"tasks", "approvals", "monitor"}
API_KEY_PREFIX = "ak_"


@dataclass
class Device:
    device_id: str
    name: str
    device_type: str
    api_key_hash: str
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    is_revoked: bool = False
    capabilities: list[str] = field(default_factory=lambda: ["tasks", "monitor"])


class DeviceStore:
    """Manages device registration, API key validation, and JSONL persistence."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._devices: dict[str, Device] = {}
        self._hash_to_id: dict[str, str] = {}
        self._load()

    # -- Public API -----------------------------------------------------------

    def register(
        self,
        name: str,
        device_type: str = "other",
        capabilities: list[str] | None = None,
    ) -> tuple[Device, str]:
        """Register a new device.

        Returns ``(device, raw_api_key)``. The raw key is only available at
        registration time — store it securely.
        """
        if device_type not in VALID_DEVICE_TYPES:
            device_type = "other"

        caps = capabilities or ["tasks", "monitor"]
        caps = [c for c in caps if c in VALID_CAPABILITIES]
        if not caps:
            caps = ["monitor"]

        raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        key_hash = _hash_key(raw_key)

        device = Device(
            device_id=uuid.uuid4().hex[:12],
            name=name,
            device_type=device_type,
            api_key_hash=key_hash,
            capabilities=caps,
        )

        self._devices[device.device_id] = device
        self._hash_to_id[key_hash] = device.device_id
        self._persist("registered", device)

        logger.info(f"Device registered: {device.device_id} ({device.name}, {device.device_type})")
        return device, raw_key

    def validate_api_key(self, raw_key: str) -> Device | None:
        """Validate an API key and return the associated device, or ``None``."""
        if not raw_key.startswith(API_KEY_PREFIX):
            return None

        key_hash = _hash_key(raw_key)
        device_id = self._hash_to_id.get(key_hash)
        if not device_id:
            return None

        device = self._devices.get(device_id)
        if not device or device.is_revoked:
            return None

        device.last_seen = time.time()
        return device

    def revoke(self, device_id: str) -> bool:
        """Revoke a device's API key. Returns True if the device existed."""
        device = self._devices.get(device_id)
        if not device:
            return False
        device.is_revoked = True
        self._persist("revoked", device)
        logger.info(f"Device revoked: {device_id} ({device.name})")
        return True

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def list_devices(self) -> list[Device]:
        return list(self._devices.values())

    # -- Persistence ----------------------------------------------------------

    def _persist(self, event_type: str, device: Device):
        """Append an event to the JSONL store (non-blocking when event loop is running)."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            **asdict(device),
        }
        line = json.dumps(entry, default=str) + "\n"

        def _write():
            try:
                with open(self._path, "a") as f:
                    f.write(line)
            except OSError as e:
                logger.error(f"Failed to write device store: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _write)
        except RuntimeError:
            # No running event loop (e.g., during tests) — write synchronously
            _write()

    def _load(self):
        """Replay JSONL events to rebuild in-memory state."""
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed device store entry")
                        continue

                    event = entry.get("event")
                    device_id = entry.get("device_id", "")

                    if event == "registered":
                        device = Device(
                            device_id=device_id,
                            name=entry.get("name", ""),
                            device_type=entry.get("device_type", "other"),
                            api_key_hash=entry.get("api_key_hash", ""),
                            created_at=entry.get("created_at", 0),
                            last_seen=entry.get("last_seen", 0),
                            is_revoked=entry.get("is_revoked", False),
                            capabilities=entry.get("capabilities", ["monitor"]),
                        )
                        self._devices[device_id] = device
                        if device.api_key_hash:
                            self._hash_to_id[device.api_key_hash] = device_id

                    elif event == "revoked" and device_id in self._devices:
                        self._devices[device_id].is_revoked = True

        except OSError as e:
            logger.error(f"Failed to load device store: {e}")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of an API key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
