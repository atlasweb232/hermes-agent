import json

from hermes_cli.runtime_urgent_notify import (
    UrgentNotification,
    event_is_urgent,
    notification_from_event,
    resolve_urgent_target,
    send_urgent_notification,
)


def test_resolve_urgent_target_prefers_slack_specific_channel(monkeypatch):
    monkeypatch.setenv("SLACK_HOME_CHANNEL", "CHOME")
    monkeypatch.setenv("HERMES_URGENT_CHANNEL", "CGENERIC")
    monkeypatch.setenv("SLACK_URGENT_CHANNEL", "CURGENT")

    assert resolve_urgent_target("slack") == "slack:CURGENT"


def test_event_is_urgent_detects_stoppage_status():
    assert event_is_urgent({"status": "blocked"})
    assert event_is_urgent({"payload": {"severity": "fallback_exhausted"}})
    assert not event_is_urgent({"status": "running", "payload": {"severity": "info"}})


def test_notification_from_event_preserves_task_metadata():
    notification = notification_from_event({
        "kind": "worker_degraded",
        "status": "degraded",
        "task_id": "task_1",
        "repo_id": "atlasweb-mini",
        "worker_id": "claude-code",
        "message": "Claude returned empty output.",
    })

    assert notification.severity == "degraded"
    assert notification.task_id == "task_1"
    assert notification.repo_id == "atlasweb-mini"
    assert notification.worker_id == "claude-code"
    assert "Claude returned empty output." in notification.to_message()


def test_send_urgent_notification_uses_configured_target(monkeypatch):
    monkeypatch.setenv("SLACK_URGENT_CHANNEL", "COPS")
    calls = []

    def fake_sender(payload):
        calls.append(payload)
        return json.dumps({"success": True})

    result = send_urgent_notification(
        UrgentNotification(
            severity="blocked",
            title="task blocked",
            message="worker exhausted fallback budget",
            task_id="task_1",
        ),
        sender=fake_sender,
    )

    assert result["status"] == "sent"
    assert calls[0]["target"] == "slack:COPS"
    assert "[Hermes urgent] task blocked" in calls[0]["message"]


def test_send_urgent_notification_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_URGENT_CHANNEL", raising=False)
    monkeypatch.delenv("HERMES_URGENT_CHANNEL", raising=False)
    monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)

    result = send_urgent_notification(UrgentNotification(
        severity="blocked",
        title="task blocked",
        message="missing urgent channel",
    ))

    assert result["status"] == "skipped"
