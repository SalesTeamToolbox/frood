"""
MeatheadGear test configuration and shared fixtures.
"""

import os

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary database path for tests."""
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    yield db_path
    if db_path.exists():
        db_path.unlink()
