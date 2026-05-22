import json

from hermes_state import SessionDB


def _dump(value):
    return json.dumps(value, sort_keys=True)


def test_t346_redaction_guard_scrubs_provider_shaped_secrets():
    from hermes_cli.redaction_guard import assert_redacted, redact_text, redact_value

    payload = {
        "command": "curl -H 'Authorization: Bearer sk-testsecret1234567890'",
        "env": {
            "OPENAI_API_KEY": "sk-testsecret1234567890",
            "CEREBRAS_API_KEY": "csk-testsecret1234567890",
            "SLACK_BOT_TOKEN": "xoxb-111-222-secretvalue",
            "GITHUB_TOKEN": "ghp_1234567890abcdefghijkl",
        },
        "safe_metrics": {"total_tokens": 123, "raw_logs_loaded": False},
        "message": "api_key=sk-testsecret1234567890 password=hunter2",
    }

    redacted = redact_value(payload)
    dumped = _dump(redacted)
    assert "sk-testsecret" not in dumped
    assert "csk-testsecret" not in dumped
    assert "xoxb-111" not in dumped
    assert "ghp_" not in dumped
    assert "hunter2" not in dumped
    assert redacted["safe_metrics"]["total_tokens"] == 123
    assert redacted["safe_metrics"]["raw_logs_loaded"] is False
    assert_redacted(redacted)
    assert "sk-testsecret" not in redact_text("Authorization: Bearer sk-testsecret1234567890")


def test_t346_learning_bus_payload_is_redacted_before_storage(tmp_path):
    from hermes_cli.learning_bus import publish_learning_event

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        event = publish_learning_event(
            db,
            topic="runtime.failure",
            payload={
                "raw_stdout": "token=sk-testsecret1234567890",
                "nested": {"api_key": "csk-testsecret1234567890"},
                "summary": "Authorization: Bearer sk-testsecret1234567890",
            },
        )
        dumped = _dump(event.to_dict())
        assert "sk-testsecret" not in dumped
        assert "csk-testsecret" not in dumped
        assert "raw_stdout" in dumped
        assert "[REDACTED]" in dumped
    finally:
        db.close()


def test_t346_worker_event_and_dashboard_redaction_share_guard(tmp_path):
    from hermes_cli.operator_dashboard import _redact
    from hermes_cli.worker_event_store import list_worker_events, store_worker_event

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        event = store_worker_event(
            db,
            kind="worker_stream",
            source="terminal",
            content="stdout api_key=sk-testsecret1234567890 password=hunter2",
            payload={"provider_log": "Bearer csk-testsecret1234567890"},
        )
        dumped = _dump(event.to_dict())
        assert "sk-testsecret" not in dumped
        assert "csk-testsecret" not in dumped
        assert "hunter2" not in dumped

        listed = list_worker_events(db)
        dashboard = _redact({"message": listed[0].summary, "slack_message": "token=sk-testsecret1234567890"})
        dashboard_dump = _dump(dashboard)
        assert "sk-testsecret" not in dashboard_dump
    finally:
        db.close()


def test_t346_runtime_lesson_curator_and_corpus_redaction_use_guard():
    from hermes_cli.curator_runtime import _bounded_supervisor_failure_payload
    from hermes_cli.mlops_corpus import SFTMessageRecord
    from hermes_cli.runtime_lesson_capture import redact_sensitive_text

    assert "sk-testsecret" not in redact_sensitive_text("run --token sk-testsecret1234567890")

    bounded = _bounded_supervisor_failure_payload(
        {
            "id": "memrec-a",
            "payload_json": {
                "output_excerpt": "api_key=sk-testsecret1234567890",
                "error_excerpt": "Bearer csk-testsecret1234567890",
                "validation_mismatch": {"password": "hunter2"},
            },
        }
    )
    bounded_dump = _dump(bounded)
    assert "sk-testsecret" not in bounded_dump
    assert "csk-testsecret" not in bounded_dump
    assert "hunter2" not in bounded_dump

    record = SFTMessageRecord(
        dataset_family="failure_repair",
        messages=[{"role": "user", "content": "token=sk-testsecret1234567890"}],
        metadata={"api_key": "csk-testsecret1234567890"},
    ).to_dict()
    record_dump = _dump(record)
    assert "sk-testsecret" not in record_dump
    assert "csk-testsecret" not in record_dump


def test_t346_slack_urgent_notification_message_is_redacted():
    from hermes_cli.runtime_urgent_notify import UrgentNotification

    notification = UrgentNotification(
        severity="blocked",
        title="worker blocked token=sk-testsecret1234567890",
        message="provider failed with Authorization: Bearer csk-testsecret1234567890",
        task_id="task-a",
    )
    dumped = _dump(notification.to_dict())
    message = notification.to_message()
    assert "sk-testsecret" not in dumped
    assert "csk-testsecret" not in dumped
    assert "sk-testsecret" not in message
    assert "csk-testsecret" not in message

