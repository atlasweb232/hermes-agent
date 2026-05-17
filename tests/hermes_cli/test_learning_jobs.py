from pathlib import Path

from hermes_cli.learning_jobs import (
    ensure_learning_jobs_schema,
    get_learning_job,
    list_learning_jobs,
    record_learning_job,
    update_learning_job,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_learning_jobs_schema_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    try:
        ensure_learning_jobs_schema(db)
        ensure_learning_jobs_schema(db)

        row = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hermes_learning_jobs'"
        ).fetchone()

        assert row is not None
    finally:
        db.close()


def test_record_update_and_list_learning_jobs(tmp_path):
    db = _make_db(tmp_path)
    try:
        created = record_learning_job(
            db,
            job_type="judge",
            status="running",
            owner="codex",
            tenant_id="atlas",
            repo_id="atlasweb-mini",
            metrics={"scanned": 1},
        )

        assert created.id.startswith("job_")
        assert created.status == "running"
        assert created.metrics_json["scanned"] == 1

        updated = update_learning_job(
            db,
            created.id,
            status="completed",
            metrics={"approved": 1},
        )

        assert updated is not None
        assert updated.status == "completed"
        assert updated.finished_at is not None
        assert get_learning_job(db, created.id).metrics_json["approved"] == 1

        jobs = list_learning_jobs(db, tenant_id="atlas", repo_id="atlasweb-mini")
        assert [job.id for job in jobs] == [created.id]
    finally:
        db.close()

