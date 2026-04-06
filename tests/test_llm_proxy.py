"""Tests for LLM proxy endpoints."""

import os
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.server import create_app


def _make_client(**kwargs) -> TestClient:
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "channel_manager": None,
        "device_store": None,
        "heartbeat": None,
        "key_store": None,
        "app_manager": MagicMock(),
        "project_manager": MagicMock(),
        "repo_manager": MagicMock(),
        "profile_loader": None,
        "github_account_store": None,
        "memory_store": None,
        "effectiveness_store": None,
        "agent_manager": None,
        "reward_system": None,
        "workspace_registry": None,
        "standalone": True,
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    return TestClient(app)


def test_llm_models_endpoint():
    """LLM-01: GET /llm/models returns available models."""
    client = _make_client()
    resp = client.get("/llm/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert len(data["data"]) > 0
    model_ids = [m["id"] for m in data["data"]]
    assert "qwen3.6-plus-free" in model_ids
    print(f"✓ LLM-01: /llm/models returns {len(data['data'])} models")


def test_llm_models_v1_endpoint():
    """LLM-02: GET /llm/v1/models works as alias."""
    client = _make_client()
    resp = client.get("/llm/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    print(f"✓ LLM-02: /llm/v1/models works as alias")


def test_llm_config_endpoint():
    """LLM-03: GET /llm/config returns proxy configuration."""
    client = _make_client()
    resp = client.get("/llm/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "endpoint" in data
    assert "default_model" in data
    assert "available_models" in data
    print(f"✓ LLM-03: /llm/config returns proxy config")


def test_llm_chat_completions_requires_json():
    """LLM-04: POST /llm/chat/completions validates JSON body."""
    client = _make_client()
    resp = client.post("/llm/chat/completions", data="not json")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    print(f"✓ LLM-04: /llm/chat/completions validates JSON")


def test_llm_chat_completions_no_model():
    """LLM-05: POST /llm/chat/completions handles missing model gracefully."""
    client = _make_client()
    resp = client.post(
        "/llm/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data or "choices" in data
    print(f"✓ LLM-05: /llm/chat/completions handles missing model")


if __name__ == "__main__":
    test_llm_models_endpoint()
    test_llm_models_v1_endpoint()
    test_llm_config_endpoint()
    test_llm_chat_completions_requires_json()
    test_llm_chat_completions_no_model()
    print("\n✓ All LLM proxy tests passed!")
