"""Setup bookkeeping coverage for the runtime learning Spec Kit."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_state import SessionDB


def test_global_hermetic_fixture_isolates_hermes_home_and_state_db(tmp_path):
    """T003 is satisfied by the global autouse fixture plus this regression proof."""
    hermes_home = get_hermes_home()

    assert hermes_home == tmp_path / "hermes_test"
    assert os.environ["HERMES_HOME"] == str(hermes_home)
    assert (hermes_home / "sessions").is_dir()
    assert (hermes_home / "cron").is_dir()
    assert (hermes_home / "memories").is_dir()
    assert (hermes_home / "skills").is_dir()

    real_user_state_db = Path.home() / ".hermes" / "state.db"
    db = SessionDB()
    try:
        assert db.db_path == hermes_home / "state.db"
        assert db.db_path != real_user_state_db
        assert db.db_path.exists()

        db.create_session("setup-bookkeeping-session", source="test")
        session = db.get_session("setup-bookkeeping-session")

        assert session is not None
        assert session["id"] == "setup-bookkeeping-session"
        assert session["source"] == "test"
    finally:
        db.close()
