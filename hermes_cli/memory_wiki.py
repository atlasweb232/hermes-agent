"""Evidence-backed memory wiki and training corpus export helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional

from hermes_state import SessionDB


DATASET_FAMILIES = {
    "repo_migration_plan",
    "migration_failure_repair",
    "before_after_diff",
    "validation_recipe",
    "architecture_pattern",
    "policy_playbook",
}

SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"),
]


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _json_loads(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "").strip().casefold() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _contains_secret(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False) if not isinstance(value, str) else value
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _compact_text(*parts: Any, limit: int = 1200) -> str:
    text = " ".join(str(part).strip() for part in parts if part).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


@dataclass
class MemoryWikiClaim:
    id: str
    title: str
    claim: str
    kind: str
    status: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    scope_json: Dict[str, Any] = field(default_factory=dict)
    evidence_json: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    safety_json: Dict[str, Any] = field(default_factory=dict)
    index_payload_json: Dict[str, Any] = field(default_factory=dict)
    training_payload_json: Dict[str, Any] = field(default_factory=dict)
    source_candidate_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingCorpusRecord:
    id: str
    source_wiki_claim_id: str
    dataset_family: str
    goal: str
    scope_json: Dict[str, Any]
    payload_json: Dict[str, Any]
    safety_json: Dict[str, Any]
    evidence_refs_json: Dict[str, Any]
    approval_provenance_json: Dict[str, Any]
    confidence: float
    export_status: str = "candidate"
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryWikiCompileResult:
    status: str
    scanned: int
    claims_created: int
    claims_updated: int
    claims: List[MemoryWikiClaim] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "claims": [claim.to_dict() for claim in self.claims],
        }


@dataclass
class TrainingCorpusExportResult:
    status: str
    scanned: int
    records_created: int
    records_updated: int
    records: List[TrainingCorpusRecord] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "records": [record.to_dict() for record in self.records],
        }


def ensure_memory_wiki_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_memory_wiki_claims (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                claim TEXT NOT NULL,
                scope_json TEXT,
                evidence_json TEXT,
                confidence REAL,
                status TEXT NOT NULL,
                safety_json TEXT,
                index_payload_json TEXT,
                training_payload_json TEXT,
                source_candidate_ids TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_memory_wiki_scope
                ON hermes_memory_wiki_claims(tenant_id, repo_id, kind, status, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_training_corpus_records (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                source_wiki_claim_id TEXT NOT NULL,
                dataset_family TEXT NOT NULL,
                goal TEXT NOT NULL,
                scope_json TEXT,
                payload_json TEXT,
                safety_json TEXT,
                evidence_refs_json TEXT,
                approval_provenance_json TEXT,
                confidence REAL,
                export_status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_training_corpus_scope
                ON hermes_training_corpus_records(tenant_id, repo_id, dataset_family, export_status, updated_at DESC)
            """
        )

    db._execute_write(_do)


def _row_to_wiki_claim(row: Any) -> MemoryWikiClaim:
    source_ids = []
    try:
        parsed = json.loads(row["source_candidate_ids"] or "[]")
        source_ids = parsed if isinstance(parsed, list) else []
    except Exception:
        source_ids = []
    return MemoryWikiClaim(
        id=row["id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        kind=row["kind"],
        title=row["title"],
        claim=row["claim"],
        scope_json=_json_loads(row["scope_json"]),
        evidence_json=_json_loads(row["evidence_json"]),
        confidence=float(row["confidence"] or 0.0),
        status=row["status"],
        safety_json=_json_loads(row["safety_json"]),
        index_payload_json=_json_loads(row["index_payload_json"]),
        training_payload_json=_json_loads(row["training_payload_json"]),
        source_candidate_ids=[str(item) for item in source_ids],
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
    )


def _row_to_training_record(row: Any) -> TrainingCorpusRecord:
    return TrainingCorpusRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        source_wiki_claim_id=row["source_wiki_claim_id"],
        dataset_family=row["dataset_family"],
        goal=row["goal"],
        scope_json=_json_loads(row["scope_json"]),
        payload_json=_json_loads(row["payload_json"]),
        safety_json=_json_loads(row["safety_json"]),
        evidence_refs_json=_json_loads(row["evidence_refs_json"]),
        approval_provenance_json=_json_loads(row["approval_provenance_json"]),
        confidence=float(row["confidence"] or 0.0),
        export_status=row["export_status"],
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
    )


def _candidate_scope(candidate: Dict[str, Any]) -> Dict[str, Any]:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    return {
        "tenant_id": candidate.get("tenant_id"),
        "repo_id": candidate.get("repo_id"),
        "tool": evidence.get("tool") or evidence.get("working_path") or evidence.get("failed_path"),
        "task_type": evidence.get("task_type") or candidate.get("kind"),
        "platform": evidence.get("platform"),
        "provider_model": evidence.get("provider_model"),
        "cross_tenant_shareable": bool(evidence.get("cross_tenant_shareable", False)),
    }


def _dataset_family_for_candidate(candidate: Dict[str, Any]) -> str:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    explicit = str(evidence.get("dataset_family") or "").strip()
    if explicit in DATASET_FAMILIES:
        return explicit
    kind = str(candidate.get("kind") or "")
    claim = str(candidate.get("claim") or "").casefold()
    if kind in {"validation_recipe", "recovery_hint"}:
        return "migration_failure_repair" if "failed" in claim or "error" in claim else "validation_recipe"
    if kind in {"routing_hint", "command_repair_policy", "playbook", "memory_rule"}:
        return "policy_playbook"
    return "policy_playbook"


def _wiki_payload_from_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    dataset_family = _dataset_family_for_candidate(candidate)
    scope = _candidate_scope(candidate)
    claim = str(candidate.get("claim") or "").strip()
    evidence_refs = {
        "candidate_id": candidate.get("id"),
        "evidence_uri": evidence.get("evidence_uri"),
        "evidence_sha256": evidence.get("evidence_sha256"),
        "record_id": evidence.get("record_id"),
        "packet_id": evidence.get("packet_id"),
        "policy_audit_id": evidence.get("policy_audit_id"),
    }
    training_payload = {
        "dataset_family": dataset_family,
        "goal": evidence.get("goal") or claim,
        "legacy_repo_ref": evidence.get("legacy_repo_ref") or evidence.get("source_repo") or {},
        "target_repo_ref": evidence.get("target_repo_ref") or evidence.get("target_repo") or {},
        "spec_refs": evidence.get("spec_refs") or [],
        "diff_refs": evidence.get("diff_refs") or {},
        "failure_signature": evidence.get("failure_signature") or evidence.get("failed_path"),
        "bad_action": evidence.get("bad_action"),
        "successful_action": evidence.get("successful_action") or evidence.get("working_path") or claim,
        "validation_evidence": evidence.get("validation_evidence") or evidence.get("validation") or {},
        "drift_eval": evidence.get("drift_eval") or {},
        "training_labels": evidence.get("training_labels") or [dataset_family],
    }
    safety = {
        "secret_safe": not _contains_secret({"claim": claim, "evidence": evidence}),
        "raw_transcript": bool(evidence.get("raw_transcript", False)),
        "raw_log": bool(evidence.get("raw_log", False)),
        "cross_tenant_shareable": scope["cross_tenant_shareable"],
        "redaction_status": evidence.get("redaction_status") or "not_required",
    }
    index_payload = {
        "text": _compact_text(claim, evidence.get("failed_path"), evidence.get("working_path")),
        "kind": candidate.get("kind"),
        "dataset_family": dataset_family,
        "scope": scope,
        "failure_signature": training_payload["failure_signature"],
        "success_signature": training_payload["successful_action"],
        "evidence_summary": evidence_refs,
    }
    return {
        "scope": scope,
        "evidence_refs": evidence_refs,
        "training_payload": training_payload,
        "safety": safety,
        "index_payload": index_payload,
    }


def compile_memory_wiki(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
    limit: int = 50,
) -> MemoryWikiCompileResult:
    ensure_memory_wiki_schema(db)
    allowed = [str(status) for status in (statuses or ["approved", "applied"]) if status]
    scanned = 0
    created = 0
    updated = 0
    claims: List[MemoryWikiClaim] = []
    errors: List[str] = []
    for status in allowed:
        for candidate in db.list_meta_candidates(
            tenant_id=tenant_id,
            repo_id=repo_id,
            status=status,
            limit=limit,
        ):
            scanned += 1
            try:
                payload = _wiki_payload_from_candidate(candidate)
                claim_text = str(candidate.get("claim") or "").strip()
                if not claim_text:
                    continue
                claim_id = _stable_id(
                    "wikiclaim",
                    candidate.get("kind"),
                    claim_text,
                    candidate.get("tenant_id"),
                    candidate.get("repo_id"),
                )
                existing = get_memory_wiki_claim(db, claim_id)
                if existing is None:
                    created += 1
                else:
                    updated += 1
                now = _now()
                title = claim_text[:120]
                confidence = max(0.0, min(1.0, float(candidate.get("score") or 0.0)))
                source_ids = sorted({str(candidate.get("id") or "")} - {""})
                def _do(conn):
                    conn.execute(
                        """
                        INSERT INTO hermes_memory_wiki_claims (
                            id, tenant_id, repo_id, kind, title, claim, scope_json,
                            evidence_json, confidence, status, safety_json,
                            index_payload_json, training_payload_json,
                            source_candidate_ids, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            tenant_id = excluded.tenant_id,
                            repo_id = excluded.repo_id,
                            kind = excluded.kind,
                            title = excluded.title,
                            claim = excluded.claim,
                            scope_json = excluded.scope_json,
                            evidence_json = excluded.evidence_json,
                            confidence = excluded.confidence,
                            status = excluded.status,
                            safety_json = excluded.safety_json,
                            index_payload_json = excluded.index_payload_json,
                            training_payload_json = excluded.training_payload_json,
                            source_candidate_ids = excluded.source_candidate_ids,
                            updated_at = excluded.updated_at
                        """
                        ,
                        (
                            claim_id,
                            candidate.get("tenant_id"),
                            candidate.get("repo_id"),
                            str(candidate.get("kind") or "playbook"),
                            title,
                            claim_text,
                            _json_dumps(payload["scope"]),
                            _json_dumps(payload["evidence_refs"]),
                            confidence,
                            _json_dumps(payload["safety"]),
                            _json_dumps(payload["index_payload"]),
                            _json_dumps(payload["training_payload"]),
                            json.dumps(source_ids, sort_keys=True),
                            now,
                            now,
                        ),
                    )

                db._execute_write(_do)
                claim = get_memory_wiki_claim(db, claim_id)
                if claim is not None:
                    claims.append(claim)
                    _index_wiki_claim(db, claim)
            except Exception as exc:
                errors.append(f"{candidate.get('id')}: {exc}")
    try:
        from hermes_cli.learning_bus import publish_learning_event_safely
        from hermes_cli.learning_jobs import record_learning_job

        record_learning_job(
            db,
            job_type="wiki",
            status="completed" if not errors else "failed",
            tenant_id=tenant_id,
            repo_id=repo_id,
            metrics={
                "scanned": scanned,
                "claims_created": created,
                "claims_updated": updated,
                "errors": len(errors),
            },
        )
        publish_learning_event_safely(
            db,
            topic="learning.wiki.compiled",
            payload={"scanned": scanned, "claims_created": created, "claims_updated": updated},
            tenant_id=tenant_id,
            repo_id=repo_id,
            event_key=f"wiki:{tenant_id or ''}:{repo_id or ''}:{int(_now())}",
        )
    except Exception:
        pass
    return MemoryWikiCompileResult(
        status="completed" if not errors else "completed_with_errors",
        scanned=scanned,
        claims_created=created,
        claims_updated=updated,
        claims=claims,
        errors=errors,
        metrics={"statuses": allowed},
    )


def _index_wiki_claim(db: SessionDB, claim: MemoryWikiClaim) -> None:
    try:
        from hermes_cli.memory_graph import upsert_graph_edge, upsert_graph_node
        from hermes_cli.memory_index import upsert_memory_index_document

        metadata = {
            **claim.scope_json,
            "tenant_id": claim.tenant_id,
            "repo_id": claim.repo_id,
            "status": claim.status,
            "task_type": claim.kind,
            "tool": claim.scope_json.get("tool"),
            "tier": "warm",
            "wiki_claim_id": claim.id,
            "confidence": claim.confidence,
        }
        upsert_memory_index_document(
            db,
            memory_id=claim.id,
            text=claim.index_payload_json.get("text") or claim.claim,
            metadata=metadata,
        )
        upsert_graph_node(db, node_id=claim.id, kind="wiki_claim", label=claim.title)
        for key, node_kind in (("tenant_id", "tenant"), ("repo_id", "repo"), ("tool", "tool")):
            value = metadata.get(key)
            if value:
                node_id = f"{node_kind}:{value}"
                upsert_graph_node(db, node_id=node_id, kind=node_kind, label=str(value))
                upsert_graph_edge(db, source_id=claim.id, target_id=node_id, relation="APPLIES_TO")
    except Exception:
        return


def get_memory_wiki_claim(db: SessionDB, claim_id: str) -> Optional[MemoryWikiClaim]:
    ensure_memory_wiki_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_memory_wiki_claims WHERE id = ?",
        (claim_id,),
    ).fetchone()
    return _row_to_wiki_claim(row) if row is not None else None


def list_memory_wiki_claims(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[MemoryWikiClaim]:
    ensure_memory_wiki_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in (("tenant_id", tenant_id), ("repo_id", repo_id), ("status", status)):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_memory_wiki_claims
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row_to_wiki_claim(row) for row in rows]


def validate_training_export(claim: MemoryWikiClaim) -> List[str]:
    errors: List[str] = []
    payload = claim.training_payload_json or {}
    family = str(payload.get("dataset_family") or "")
    if family not in DATASET_FAMILIES:
        errors.append("unsupported_dataset_family")
    if not claim.evidence_json:
        errors.append("missing_evidence_refs")
    safety = claim.safety_json or {}
    if safety.get("secret_safe") is not True:
        errors.append("secret_safety_not_confirmed")
    if safety.get("raw_transcript") or safety.get("raw_log"):
        errors.append("raw_transcript_or_log_not_exportable")
    if _contains_secret({"claim": claim.claim, "payload": payload, "evidence": claim.evidence_json}):
        errors.append("secret_pattern_detected")
    return errors


def build_training_corpus_record(
    claim: MemoryWikiClaim,
    *,
    approve: bool = False,
) -> TrainingCorpusRecord:
    payload = claim.training_payload_json or {}
    family = str(payload.get("dataset_family") or "policy_playbook")
    record_id = _stable_id("trainrec", claim.id, family)
    export_status = "approved" if approve else "candidate"
    return TrainingCorpusRecord(
        id=record_id,
        tenant_id=claim.tenant_id,
        repo_id=claim.repo_id,
        source_wiki_claim_id=claim.id,
        dataset_family=family,
        goal=str(payload.get("goal") or claim.claim),
        scope_json=claim.scope_json,
        payload_json={
            "claim": claim.claim,
            "legacy_repo_ref": payload.get("legacy_repo_ref") or {},
            "target_repo_ref": payload.get("target_repo_ref") or {},
            "spec_refs": payload.get("spec_refs") or [],
            "diff_refs": payload.get("diff_refs") or {},
            "failure_signature": payload.get("failure_signature"),
            "bad_action": payload.get("bad_action"),
            "successful_action": payload.get("successful_action"),
            "validation_evidence": payload.get("validation_evidence") or {},
            "training_labels": payload.get("training_labels") or [family],
            "drift_eval": payload.get("drift_eval") or {},
        },
        safety_json={
            **claim.safety_json,
            "export_validated_at": _now(),
        },
        evidence_refs_json=claim.evidence_json,
        approval_provenance_json={
            "source": "memory_wiki",
            "approval_required": True,
            "operator_approved": approve,
        },
        confidence=claim.confidence,
        export_status=export_status,
    )


def upsert_training_corpus_record(db: SessionDB, record: TrainingCorpusRecord) -> TrainingCorpusRecord:
    ensure_memory_wiki_schema(db)
    now = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_training_corpus_records (
                id, tenant_id, repo_id, source_wiki_claim_id, dataset_family,
                goal, scope_json, payload_json, safety_json, evidence_refs_json,
                approval_provenance_json, confidence, export_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                source_wiki_claim_id = excluded.source_wiki_claim_id,
                dataset_family = excluded.dataset_family,
                goal = excluded.goal,
                scope_json = excluded.scope_json,
                payload_json = excluded.payload_json,
                safety_json = excluded.safety_json,
                evidence_refs_json = excluded.evidence_refs_json,
                approval_provenance_json = excluded.approval_provenance_json,
                confidence = excluded.confidence,
                export_status = excluded.export_status,
                updated_at = excluded.updated_at
            """
            ,
            (
                record.id,
                record.tenant_id,
                record.repo_id,
                record.source_wiki_claim_id,
                record.dataset_family,
                record.goal,
                _json_dumps(record.scope_json),
                _json_dumps(record.payload_json),
                _json_dumps(record.safety_json),
                _json_dumps(record.evidence_refs_json),
                _json_dumps(record.approval_provenance_json),
                record.confidence,
                record.export_status,
                now,
                now,
            ),
        )

    db._execute_write(_do)
    row = db._conn.execute(
        "SELECT * FROM hermes_training_corpus_records WHERE id = ?",
        (record.id,),
    ).fetchone()
    return _row_to_training_record(row)


def export_training_corpus(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    dataset_family: Optional[str] = None,
    approve: bool = False,
    limit: int = 50,
) -> TrainingCorpusExportResult:
    ensure_memory_wiki_schema(db)
    claims = list_memory_wiki_claims(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        status="active",
        limit=limit,
    )
    created = 0
    updated = 0
    records: List[TrainingCorpusRecord] = []
    rejected: List[Dict[str, Any]] = []
    for claim in claims:
        family = str((claim.training_payload_json or {}).get("dataset_family") or "")
        if dataset_family and family != dataset_family:
            continue
        errors = validate_training_export(claim)
        if errors:
            rejected.append({"wiki_claim_id": claim.id, "errors": errors})
            continue
        record = build_training_corpus_record(claim, approve=approve)
        existing = get_training_corpus_record(db, record.id)
        if existing is None:
            created += 1
        else:
            updated += 1
        records.append(upsert_training_corpus_record(db, record))
    try:
        from hermes_cli.learning_bus import publish_learning_event_safely
        from hermes_cli.learning_jobs import record_learning_job

        metrics = {
            "scanned": len(claims),
            "records_created": created,
            "records_updated": updated,
            "rejected": len(rejected),
            "dataset_family": dataset_family,
        }
        record_learning_job(
            db,
            job_type="training_export",
            status="completed",
            tenant_id=tenant_id,
            repo_id=repo_id,
            metrics=metrics,
        )
        publish_learning_event_safely(
            db,
            topic="learning.training_corpus.exported",
            payload=metrics,
            tenant_id=tenant_id,
            repo_id=repo_id,
            event_key=f"training:{tenant_id or ''}:{repo_id or ''}:{dataset_family or 'all'}:{int(_now())}",
        )
    except Exception:
        pass
    return TrainingCorpusExportResult(
        status="completed",
        scanned=len(claims),
        records_created=created,
        records_updated=updated,
        records=records,
        rejected=rejected,
        metrics={"dataset_family": dataset_family, "approve": approve},
    )


def get_training_corpus_record(db: SessionDB, record_id: str) -> Optional[TrainingCorpusRecord]:
    ensure_memory_wiki_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_training_corpus_records WHERE id = ?",
        (record_id,),
    ).fetchone()
    return _row_to_training_record(row) if row is not None else None


def list_training_corpus_records(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    dataset_family: Optional[str] = None,
    export_status: Optional[str] = None,
    limit: int = 50,
) -> List[TrainingCorpusRecord]:
    ensure_memory_wiki_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in (
        ("tenant_id", tenant_id),
        ("repo_id", repo_id),
        ("dataset_family", dataset_family),
        ("export_status", export_status),
    ):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_training_corpus_records
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row_to_training_record(row) for row in rows]
