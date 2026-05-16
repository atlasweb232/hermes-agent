# Data Model

## observability_events

Append-only event table.

```sql
CREATE TABLE observability_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  timestamp TEXT NOT NULL,
  source TEXT NOT NULL,
  tenant TEXT,
  board TEXT,
  task_id TEXT,
  parent_task_id TEXT,
  run_id TEXT,
  session_id TEXT,
  worker_id TEXT,
  worker_kind TEXT,
  provider TEXT,
  model TEXT,
  repo_path TEXT,
  branch TEXT,
  severity TEXT NOT NULL DEFAULT 'info',
  status TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  redactions_json TEXT NOT NULL DEFAULT '[]',
  correlation_id TEXT
);
```

Indexes:

```sql
CREATE INDEX idx_obs_events_task_time ON observability_events(task_id, timestamp);
CREATE INDEX idx_obs_events_time ON observability_events(timestamp);
CREATE INDEX idx_obs_events_repo_time ON observability_events(repo_path, timestamp);
CREATE INDEX idx_obs_events_status_time ON observability_events(status, timestamp);
CREATE INDEX idx_obs_events_worker_time ON observability_events(worker_id, timestamp);
CREATE INDEX idx_obs_events_correlation ON observability_events(correlation_id);
```

## task_rollups

Derived table. Rebuildable from events + Kanban DB.

```sql
CREATE TABLE task_rollups (
  task_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  tenant TEXT,
  board TEXT,
  repo_path TEXT,
  branch TEXT,
  assignee TEXT,
  worker_kind TEXT,
  provider TEXT,
  model TEXT,
  gate_status TEXT,
  blocker TEXT,
  last_event_type TEXT,
  created_at TEXT,
  updated_at TEXT,
  started_at TEXT,
  completed_at TEXT,
  runtime_seconds REAL
);
```

## worker_rollups

Derived table. Rebuildable from worker/session events.

```sql
CREATE TABLE worker_rollups (
  worker_id TEXT PRIMARY KEY,
  task_id TEXT,
  session_id TEXT,
  worker_kind TEXT,
  provider TEXT,
  model TEXT,
  status TEXT,
  current_tool TEXT,
  heartbeat_at TEXT,
  started_at TEXT,
  updated_at TEXT
);
```

## gate_rollups

Derived latest gate state by task/run.

```sql
CREATE TABLE gate_rollups (
  gate_run_id TEXT PRIMARY KEY,
  task_id TEXT,
  run_id TEXT,
  repo_path TEXT,
  branch TEXT,
  status TEXT NOT NULL,
  required_checks_json TEXT NOT NULL,
  failed_checks_json TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT
);
```

