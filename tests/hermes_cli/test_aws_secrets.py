import json
import subprocess

from hermes_cli.aws_secrets import check_secret_references, describe_secret_reference


def test_describe_secret_reference_uses_describe_only(monkeypatch):
    calls = []

    def fake_run(command, check, capture_output, text, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"ARN": "arn:aws:secretsmanager:us-east-1:1:secret:test", "LastChangedDate": "now"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = describe_secret_reference("hermes/test", profile="atlas", region="us-east-1")

    assert result.exists is True
    assert result.status == "ok"
    command = calls[0]
    assert command[:5] == ["aws", "--profile", "atlas", "--region", "us-east-1"]
    assert "describe-secret" in command
    assert "get-secret-value" not in command


def test_check_secret_references_reports_incomplete_on_missing(monkeypatch):
    def fake_run(command, check, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            command,
            254,
            stdout="",
            stderr="ResourceNotFoundException: secret missing",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = check_secret_references(["missing/secret"])

    assert result["status"] == "incomplete"
    assert result["secrets"][0]["status"] == "missing"
    assert result["secrets"][0]["exists"] is False
