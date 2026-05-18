"""Tests for TinyFish Browser/Agent Hermes tools."""

import importlib


def test_tinyfish_tools_register_as_first_class_toolset():
    import tools.tinyfish_browser  # noqa: F401
    from tools.registry import registry

    expected = {
        "tinyfish_fetch",
        "tinyfish_search",
        "tinyfish_agent_run",
        "tinyfish_agent_queue",
        "tinyfish_run_status",
    }

    assert set(registry.get_tool_names_for_toolset("tinyfish")) == expected
    for name in expected:
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.toolset == "tinyfish"
        assert entry.requires_env == ["TINYFISH_API_KEY"]
        assert entry.check_fn is tools.tinyfish_browser._check_requirements


def test_tinyfish_check_requires_env_api_key(monkeypatch):
    tinyfish_tools = importlib.import_module("tools.tinyfish_browser")

    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    assert tinyfish_tools._check_requirements() is False

    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    assert tinyfish_tools._check_requirements() is True


def test_tinyfish_client_reads_api_key_from_environment(monkeypatch):
    tinyfish_tools = importlib.import_module("tools.tinyfish_browser")
    seen = {}

    class FakeTinyFish:
        def __init__(self, api_key=None, timeout=None):
            seen["api_key"] = api_key
            seen["timeout"] = timeout

    monkeypatch.setenv("TINYFISH_API_KEY", "env-only-key")
    monkeypatch.setattr("tinyfish.TinyFish", FakeTinyFish)

    tinyfish_tools._client(timeout=42)

    assert seen == {"api_key": "env-only-key", "timeout": 42.0}
