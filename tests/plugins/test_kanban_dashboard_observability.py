from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.learning_jobs import record_learning_job
from hermes_state import SessionDB
from plugins.kanban.dashboard.plugin_api import router


def test_kanban_dashboard_observability_routes_are_scoped(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB()
    try:
        job = record_learning_job(
            db,
            job_type="judge",
            status="running",
            owner="codex",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-1",
            metrics={"title": "dashboard line item"},
        )
    finally:
        db.close()

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    listed = client.get("/observability/items", params={"tenant_id": "atlas", "repo_id": "repo-a"}).json()
    assert listed[0]["id"] == f"obs_job_{job.id}"

    detail = client.get(
        f"/observability/items/obs_job_{job.id}",
        params={"tenant_id": "atlas", "repo_id": "repo-a"},
    ).json()
    assert detail["line_item_id"] == f"obs_job_{job.id}"
    assert detail["raw_transcript_included"] is False

    ask = client.post(
        f"/observability/items/obs_job_{job.id}/ask",
        json={"tenant_id": "atlas", "repo_id": "repo-a", "question": "What is happening?"},
    ).json()
    assert ask["mutation_allowed"] is False

    denied = client.get(f"/observability/items/obs_job_{job.id}", params={"tenant_id": "other"})
    assert denied.status_code == 403
