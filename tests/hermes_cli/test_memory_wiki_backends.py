import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _local_config(tmp_path: Path) -> dict:
    root = tmp_path / "wiki"
    return {
        "supervisor": {
            "global_memory_wiki": {
                "enabled": True,
                "namespace": "tests",
                "object_store": {"backend": "local", "uri": str(root / "objects")},
                "state_store": {"backend": "sqlite", "uri": str(root / "state.sqlite")},
                "lexical_index": {"backend": "sqlite_fts", "uri": str(root / "lexical.sqlite")},
                "vector_index": {"backend": "local_fake", "uri": str(root / "vector.sqlite")},
                "graph_index": {"backend": "sqlite", "uri": str(root / "graph.sqlite")},
            }
        }
    }


def _approved_payload() -> dict:
    return {
        "id": "claim-1",
        "approval_state": "approved",
        "visibility": "global",
        "scope": "global",
        "shareable": True,
        "title": "Retry SQLite locked pytest once",
        "text": "When pytest reports sqlite locked, retry once after a short delay.",
        "evidence_refs": ["memory://approved/1", "wiki://claim/source"],
        "metadata": {"tenant_id": "atlas", "status": "canonical"},
    }


def test_memory_wiki_backend_factory_builds_local_fake_scaleout_adapters(tmp_path):
    from hermes_cli.memory_wiki_backends import build_memory_wiki_backends

    bundle = build_memory_wiki_backends(_local_config(tmp_path))
    health = {item.role: item.to_dict() for item in bundle.health()}

    assert set(health) == {"object", "state", "lexical", "vector", "graph"}
    assert health["object"]["backend"] == "local"
    assert health["state"]["backend"] == "sqlite"
    assert health["lexical"]["backend"] == "sqlite_fts"
    assert health["vector"]["backend"] == "local_fake"
    assert health["graph"]["backend"] == "sqlite"
    assert all(item["enabled"] for item in health.values())
    assert all(item["dependency_free"] for item in health.values())
    assert all(item["local_only"] for item in health.values())

    payload = _approved_payload()
    bundle.object_store.put_json("claims/claim-1.json", payload)
    bundle.state_store.upsert("claim-1", payload)
    bundle.lexical_index.upsert("claim-1", payload)
    bundle.vector_index.upsert("claim-1", payload)
    bundle.graph_index.upsert("claim-1", payload)

    assert bundle.object_store.get_json("claims/claim-1.json")["text"].startswith("When pytest")
    assert bundle.state_store.get("claim-1")["approval_state"] == "approved"
    assert [row["id"] for row in bundle.lexical_index.search("sqlite locked")] == ["claim-1"]
    assert [row["id"] for row in bundle.vector_index.search("sqlite locked")] == ["claim-1"]
    graph = bundle.graph_index.neighbors("claim-1")
    assert graph and graph[0]["target_id"] == "memory://approved/1"


def test_memory_wiki_backend_sanitizer_rejects_noncanonical_private_or_raw_payloads():
    from hermes_cli.memory_wiki_backends import sanitize_indexable_payload

    with pytest.raises(ValueError, match="approval_state"):
        sanitize_indexable_payload({**_approved_payload(), "approval_state": "proposed"})

    with pytest.raises(ValueError, match="shareable"):
        sanitize_indexable_payload({**_approved_payload(), "visibility": "tenant", "shareable": False})

    with pytest.raises(ValueError, match="scope"):
        sanitize_indexable_payload(
            {
                **_approved_payload(),
                "visibility": "global",
                "scope": "private",
                "shareable": True,
                "global_safe": True,
            }
        )

    with pytest.raises(ValueError, match="sensitivity"):
        sanitize_indexable_payload({**_approved_payload(), "sensitivity": "secret"})

    with pytest.raises(ValueError, match="tenant"):
        sanitize_indexable_payload(
            {
                **_approved_payload(),
                "shareable": False,
                "global_safe": False,
                "metadata": {
                    "tenant_id": "atlas",
                    "visibility": "tenant_only",
                    "status": "canonical",
                },
            }
        )

    with pytest.raises(ValueError, match="raw_transcript"):
        sanitize_indexable_payload({**_approved_payload(), "raw_transcript": "full private chat"})

    sanitized = sanitize_indexable_payload(
        {
            **_approved_payload(),
            "provider_logs": "debug log",
            "secret_note": "sk-testsecret1234567890",
            "metadata": {"password": "hunter2", "status": "canonical"},
        }
    )

    dumped = json.dumps(sanitized, sort_keys=True)
    assert "provider_logs" not in dumped
    assert "sk-testsecret" not in dumped
    assert "hunter2" not in dumped
    assert sanitized["metadata"]["password"] == "[REDACTED]"


def test_memory_wiki_backends_reject_nested_raw_payload_without_persisting(tmp_path):
    from hermes_cli.memory_wiki_backends import build_memory_wiki_backends

    bundle = build_memory_wiki_backends(_local_config(tmp_path))
    payload = {
        **_approved_payload(),
        "metadata": {
            "status": "canonical",
            "audit": {
                "raw_transcript": "PRIVATE CHAT SHOULD NOT PERSIST",
                "raw_proposal": "PRIVATE PROPOSAL SHOULD NOT PERSIST",
            },
        },
    }

    with pytest.raises(ValueError, match="raw_transcript"):
        bundle.object_store.put_json("claims/raw.json", payload)
    with pytest.raises(ValueError, match="raw_transcript"):
        bundle.state_store.upsert("raw", payload)
    with pytest.raises(ValueError, match="raw_transcript"):
        bundle.lexical_index.upsert("raw", payload)
    with pytest.raises(ValueError, match="raw_transcript"):
        bundle.vector_index.upsert("raw", payload)
    with pytest.raises(ValueError, match="raw_transcript"):
        bundle.graph_index.upsert("raw", payload)

    persisted = []
    for path in (tmp_path / "wiki").rglob("*"):
        if path.is_file():
            persisted.append(path.read_bytes())
    dumped = b"\n".join(persisted)
    assert b"PRIVATE CHAT SHOULD NOT PERSIST" not in dumped
    assert b"PRIVATE PROPOSAL SHOULD NOT PERSIST" not in dumped
    assert not (tmp_path / "wiki" / "objects" / "claims" / "raw.json").exists()
    assert bundle.state_store.get("raw") is None
    assert bundle.lexical_index.search("private chat") == []
    assert bundle.vector_index.search("private chat") == []
    assert bundle.graph_index.neighbors("raw") == []


def test_memory_wiki_unknown_production_backends_are_configured_unavailable(tmp_path):
    from hermes_cli.memory_wiki_backends import build_memory_wiki_backends

    config = _local_config(tmp_path)
    wiki = config["supervisor"]["global_memory_wiki"]
    wiki["object_store"] = {"backend": "s3", "uri": "s3://secret-bucket/path", "access_key": "AKIASECRET"}
    wiki["state_store"] = {"backend": "postgres", "uri": "postgres://user:pass@db/memory"}
    wiki["lexical_index"] = {"backend": "opensearch", "uri": "https://search.example"}
    wiki["vector_index"] = {"backend": "qdrant", "uri": "https://vectors.example"}
    wiki["graph_index"] = {"backend": "neo4j", "uri": "bolt://user:pass@graph"}

    health = [item.to_dict() for item in build_memory_wiki_backends(config).health()]

    assert {item["status"] for item in health} == {"unavailable"}
    assert all(item["enabled"] for item in health)
    assert all(not item["dependency_free"] for item in health)
    assert all("not installed" in item["reason"] for item in health)
    dumped = json.dumps(health, sort_keys=True)
    assert "AKIASECRET" not in dumped
    assert "user:pass" not in dumped


def test_memory_wiki_backends_cli_json_reports_safe_health(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import config as hermes_config
    from hermes_cli import main as hermes_main

    cfg = _local_config(tmp_path)
    cfg["supervisor"]["global_memory_wiki"]["object_store"]["uri"] = "s3://secret-bucket/path"
    cfg["supervisor"]["global_memory_wiki"]["object_store"]["backend"] = "s3"
    monkeypatch.setattr(hermes_config, "load_config", lambda: cfg)

    with patch.object(sys, "argv", ["hermes", "memory", "wiki", "backends", "--json"]):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out)
    assert {item["role"] for item in data["backends"]} == {"object", "state", "lexical", "vector", "graph"}
    object_health = next(item for item in data["backends"] if item["role"] == "object")
    assert object_health["backend"] == "s3"
    assert object_health["status"] == "unavailable"
    assert "secret-bucket" not in json.dumps(data, sort_keys=True)
