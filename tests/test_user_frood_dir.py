"""Tests for core.user_frood_dir — user-level ~/.frood/ bootstrap + cli.yaml manifest.

Verifies:
  - user_frood_dir() resolves to Path.home() / ".frood" regardless of CWD
  - user_frood_dir(create=True) creates the directory if missing
  - load_manifest() returns DEFAULT_MANIFEST when cli.yaml is absent and writes it to disk
  - load_manifest() deep-merges partial user files against DEFAULT_MANIFEST
  - save_manifest() → load_manifest() round-trips losslessly
  - A malformed cli.yaml falls back to DEFAULT_MANIFEST and logs a warning (no crash)
  - DEFAULT_MANIFEST exposes warehouse inclusion flags with sensible defaults

All tests redirect Path.home() via monkeypatch so they pass on Windows where HOME
isn't the canonical env var (HOME, USERPROFILE, and HOMEPATH all vary).
"""

import logging
from pathlib import Path


def _redirect_home(monkeypatch, tmp_path: Path) -> Path:
    """Force Path.home() → tmp_path for the duration of the test."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_user_frood_dir_returns_home_dot_frood(monkeypatch, tmp_path):
    """user_frood_dir() returns Path.home() / '.frood' regardless of CWD."""
    from core.user_frood_dir import user_frood_dir

    home = _redirect_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    result = user_frood_dir()
    assert result == home / ".frood"


def test_user_frood_dir_creates_dir_on_demand(monkeypatch, tmp_path):
    """user_frood_dir(create=True) creates the directory if it's missing."""
    from core.user_frood_dir import user_frood_dir

    home = _redirect_home(monkeypatch, tmp_path)
    target = home / ".frood"
    assert not target.exists()

    returned = user_frood_dir(create=True)
    assert returned == target
    assert target.is_dir()

    # Idempotent — calling twice with create=True is fine
    user_frood_dir(create=True)
    assert target.is_dir()


def test_load_manifest_absent_returns_defaults_and_creates_file(monkeypatch, tmp_path):
    """Missing cli.yaml → load_manifest() returns DEFAULT_MANIFEST and writes it to disk."""
    from core.user_frood_dir import DEFAULT_MANIFEST, load_manifest, user_frood_dir

    _redirect_home(monkeypatch, tmp_path)
    manifest_path = user_frood_dir() / "cli.yaml"
    assert not manifest_path.exists()

    result = load_manifest()

    # Returned dict matches DEFAULT_MANIFEST (by value)
    assert result == DEFAULT_MANIFEST
    # File was created at the expected path
    assert manifest_path.exists()
    # Returned dict is a deep copy — mutating it must not touch the module constant
    result["clis"]["claude-code"]["enabled"] = False
    assert DEFAULT_MANIFEST["clis"]["claude-code"]["enabled"] is True


def test_load_manifest_partial_fills_defaults(monkeypatch, tmp_path):
    """Partial cli.yaml → missing keys filled from DEFAULT_MANIFEST; user values preserved."""
    from core.user_frood_dir import DEFAULT_MANIFEST, load_manifest, save_manifest, user_frood_dir

    _redirect_home(monkeypatch, tmp_path)

    # Seed a partial manifest by going through save_manifest so the on-disk format
    # matches whatever serializer the implementation picked (yaml or json).
    partial = {"clis": {"claude-code": {"enabled": False}}}
    save_manifest(partial)

    # Sanity: the file exists at the manifest location
    assert (user_frood_dir() / "cli.yaml").exists()

    result = load_manifest()

    # User override preserved
    assert result["clis"]["claude-code"]["enabled"] is False
    # Missing entries filled from defaults
    assert result["clis"]["opencode"] == DEFAULT_MANIFEST["clis"]["opencode"]
    assert result["warehouse"] == DEFAULT_MANIFEST["warehouse"]


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    """save_manifest(m) → load_manifest() → identical dict."""
    from core.user_frood_dir import load_manifest, save_manifest

    _redirect_home(monkeypatch, tmp_path)

    manifest = {
        "clis": {
            "claude-code": {"enabled": True},
            "opencode": {"enabled": False, "projects": ["/tmp/proj-a", "/tmp/proj-b"]},
        },
        "warehouse": {
            "include_claude_warehouse": False,
            "include_frood_builtins": True,
        },
    }

    save_manifest(manifest)
    reloaded = load_manifest()
    assert reloaded == manifest


def test_malformed_file_falls_back_to_defaults(monkeypatch, tmp_path, caplog):
    """Malformed cli.yaml → DEFAULT_MANIFEST returned + warning logged, no crash."""
    from core.user_frood_dir import DEFAULT_MANIFEST, load_manifest, user_frood_dir

    _redirect_home(monkeypatch, tmp_path)

    manifest_path = user_frood_dir(create=True) / "cli.yaml"
    # Write garbage that is invalid in both YAML (unresolved tag) and JSON.
    manifest_path.write_text("::not valid yaml:: { broken", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="frood.user_frood_dir"):
        result = load_manifest()

    assert result == DEFAULT_MANIFEST
    assert any(
        "cli.yaml" in record.message.lower() or "malformed" in record.message.lower()
        for record in caplog.records
    ), "Expected a warning mentioning the malformed manifest"


def test_warehouse_flags_accessible():
    """DEFAULT_MANIFEST exposes warehouse inclusion flags with sensible defaults."""
    from core.user_frood_dir import DEFAULT_MANIFEST

    assert DEFAULT_MANIFEST["warehouse"]["include_claude_warehouse"] is True
    assert DEFAULT_MANIFEST["warehouse"]["include_frood_builtins"] is True
