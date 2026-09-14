"""Deterministic persistence and lifecycle helpers for marketing assessments.

This module deliberately does not synthesize a report.  It records one immutable
collection run, associates the child tasks it created, and makes the parent task
truthful while later report synthesis is added in a separate stage.
"""
import json


ASSESSMENT_SCHEMA_VERSION = 1
STAGE_ORDER = ("defend_audit", "run_brand_audit", "seo_measurement")
SYNTHESIS_STAGE = "marketing_assessment_synthesis"
PENDING_TASK_STATUSES = frozenset(("queued", "running", "collecting"))
FAILED_TASK_STATUSES = frozenset(("failed", "needs_input", "cancelled"))


def assessment_run_key(task_id, params):
    """Return a bounded, stable key supplied by the caller or scoped to its task."""
    supplied = (params or {}).get("assessment_run_key") or (params or {}).get("idempotency_key")
    if supplied is not None:
        supplied = str(supplied).strip()
        if supplied:
            return supplied[:180]
    return f"task:{int(task_id)}"


def stage_snapshot(rows):
    """Return dashboard-safe collection state without treating absent evidence as zero."""
    stages = []
    for row in rows:
        stages.append({
            "stage": row["stage_key"],
            "task_id": row["task_id"],
            "required": bool(row["required"]),
            "status": row.get("task_status") or row.get("status") or "queued",
            "error": (row.get("task_error") or "")[:500] or None,
        })
    return stages


def collection_outcome(rows, current_status="collecting"):
    """Derive a persisted lifecycle state only from child task settlement.

    A complete collection is deliberately still ``collecting`` until the future
    synthesis stage owns the transition to ``synthesizing``.  This prevents the
    parent task from claiming a finished audit merely because evidence was queued.
    """
    stages = stage_snapshot(rows)
    required = [stage for stage in stages if stage["required"]]
    pending = [stage for stage in required if stage["status"] in PENDING_TASK_STATUSES]
    failed = [stage for stage in required if stage["status"] in FAILED_TASK_STATUSES]
    unknown = [stage for stage in required if stage["status"] not in PENDING_TASK_STATUSES | FAILED_TASK_STATUSES | {"done"}]

    manifest = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "stages": stages,
        "children_settled": not pending and not unknown,
        "synthesis_eligible": not pending and not unknown and not failed,
        "report_state": "not_generated",
    }
    if pending or unknown:
        manifest["next_step"] = "collect_evidence"
        return "collecting", manifest, "collecting evidence"
    if failed:
        failed_names = ", ".join(stage["stage"] for stage in failed)
        manifest["next_step"] = "repair_or_resume_failed_stage"
        manifest["missing_evidence"] = [stage["stage"] for stage in failed]
        manifest["report_reason"] = "No validated report exists because required evidence did not settle."
        return "failed", manifest, f"assessment collection failed: {failed_names}"

    # Do not undo a future synthesis worker that has already claimed this run.
    if current_status == "synthesizing":
        manifest["next_step"] = "synthesis_in_progress"
        return "synthesizing", manifest, "synthesis in progress"
    manifest["next_step"] = "synthesize_report"
    return "collecting", manifest, "evidence collection complete; synthesis pending"


def _as_dict(row):
    return dict(row) if row is not None else None


def get_or_create_assessment(cur, *, task_id, brand_id, project_id, params):
    """Create one assessment for a parent task, or return the existing logical run.

    ``assessment_run_key`` gives callers a durable idempotency handle across
    duplicate UI submissions.  Without it, the parent task is the logical run.
    """
    params = params or {}
    run_key = assessment_run_key(task_id, params)
    brief = params.get("brief_snapshot", params.get("brief", {}))
    if not isinstance(brief, dict):
        brief = {}
    try:
        brief_version = max(1, int(params.get("brief_version", 1)))
    except (TypeError, ValueError):
        brief_version = 1

    cur.execute(
        "SELECT * FROM marketing_assessments WHERE trigger_task_id=%s FOR UPDATE",
        (task_id,),
    )
    existing = _as_dict(cur.fetchone())
    if existing:
        return existing, False, False

    cur.execute(
        "SELECT * FROM marketing_assessments WHERE brand_id=%s AND project_id=%s AND run_key=%s FOR UPDATE",
        (brand_id, project_id, run_key),
    )
    existing = _as_dict(cur.fetchone())
    if existing:
        return existing, False, True

    cur.execute(
        "SELECT id FROM marketing_assessments WHERE brand_id=%s AND project_id=%s ORDER BY id DESC LIMIT 1",
        (brand_id, project_id),
    )
    previous = _as_dict(cur.fetchone())
    prior_id = previous.get("id") if previous else None
    cur.execute(
        "INSERT INTO marketing_assessments "
        "(brand_id, project_id, trigger_task_id, run_key, schema_version, status, brief_snapshot, brief_version, prior_assessment_id, started_at) "
        "VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s,now()) ON CONFLICT DO NOTHING RETURNING *",
        (brand_id, project_id, task_id, run_key, ASSESSMENT_SCHEMA_VERSION,
         json.dumps(brief), brief_version, prior_id),
    )
    created = _as_dict(cur.fetchone())
    if created:
        return created, True, False

    # A concurrent duplicate click can win after the earlier SELECT. Re-read the
    # uniquely constrained logical run instead of raising or creating children.
    cur.execute(
        "SELECT * FROM marketing_assessments WHERE trigger_task_id=%s "
        "OR (brand_id=%s AND project_id=%s AND run_key=%s) FOR UPDATE",
        (task_id, brand_id, project_id, run_key),
    )
    existing = _as_dict(cur.fetchone())
    if not existing:
        raise RuntimeError("marketing assessment insert conflicted without a persisted logical run")
    return existing, False, existing["trigger_task_id"] != task_id


def ensure_stage_tasks(cur, *, assessment, parent_task_id, stages):
    """Create missing child tasks exactly once for an assessment under a row lock."""
    assessment_id = assessment["id"]
    cur.execute(
        "SELECT stage_key, task_id FROM marketing_assessment_stages WHERE assessment_id=%s FOR UPDATE",
        (assessment_id,),
    )
    existing = {row["stage_key"]: row["task_id"] for row in cur.fetchall()}
    child_ids = []
    for stage_key, child_params in stages:
        existing_task_id = existing.get(stage_key)
        if existing_task_id:
            child_ids.append(existing_task_id)
            continue
        payload = dict(child_params)
        payload["assessment_id"] = assessment_id
        payload["assessment_stage"] = stage_key
        cur.execute(
            "INSERT INTO tasks (type, status, params, triggered_by, parent_task_id) "
            "VALUES (%s,'queued',%s,'marketing-assessment',%s) RETURNING id",
            (stage_key, json.dumps(payload), parent_task_id),
        )
        child = _as_dict(cur.fetchone())
        if not child or not child.get("id"):
            raise RuntimeError(f"marketing assessment stage {stage_key} did not return a task id")
        child_id = child["id"]
        cur.execute(
            "INSERT INTO marketing_assessment_stages (assessment_id, stage_key, task_id, required, status) "
            "VALUES (%s,%s,%s,true,'queued')",
            (assessment_id, stage_key, child_id),
        )
        child_ids.append(child_id)
    return child_ids


def reconcile_assessment(cur, assessment_id):
    """Idempotently reflect child state onto the stored assessment and parent task."""
    cur.execute("SELECT * FROM marketing_assessments WHERE id=%s FOR UPDATE", (assessment_id,))
    assessment = _as_dict(cur.fetchone())
    if not assessment:
        return None
    cur.execute(
        "SELECT s.stage_key, s.task_id, s.required, s.status, t.status AS task_status, t.error AS task_error "
        "FROM marketing_assessment_stages s JOIN tasks t ON t.id=s.task_id "
        "WHERE s.assessment_id=%s ORDER BY s.id",
        (assessment_id,),
    )
    rows = [_as_dict(row) for row in cur.fetchall()]
    status, manifest, progress = collection_outcome(rows, assessment.get("status", "collecting"))
    # A stored validated strategy is terminal for collection reconciliation. A
    # later child callback must never erase it just because its task row changed.
    if assessment.get("status") in {"ready", "partial", "cancelled"}:
        return {"assessment_id": assessment_id, "status": assessment["status"],
                "manifest": assessment.get("source_manifest") or {},
                "progress_text": "stored strategy remains current"}

    cur.execute(
        "UPDATE marketing_assessment_stages s SET status=t.status, updated_at=now() "
        "FROM tasks t WHERE s.assessment_id=%s AND s.task_id=t.id",
        (assessment_id,),
    )
    cur.execute(
        "UPDATE marketing_assessments SET status=%s, source_manifest=%s, updated_at=now(), "
        "completed_at=CASE WHEN %s='failed' THEN now() ELSE NULL END WHERE id=%s",
        (status, json.dumps(manifest), status, assessment_id),
    )
    parent_status = "failed" if status == "failed" else "collecting"
    cur.execute(
        "UPDATE tasks SET status=%s, result_ref=%s, error=%s, progress=%s, progress_text=%s, "
        "finished_at=CASE WHEN %s='failed' THEN now() ELSE NULL END WHERE id=%s",
        (parent_status, json.dumps({"workflow": "marketing_assessment", "assessment_id": assessment_id,
                                    "status": status, "source_manifest": manifest}, separators=(",", ":"))[:20000],
         progress if status == "failed" else None,
         100 if status == "failed" else 66,
         progress, status, assessment["trigger_task_id"]),
    )
    return {"assessment_id": assessment_id, "status": status, "manifest": manifest, "progress_text": progress}


def reconcile_for_child_task(cur, child_task_id):
    cur.execute(
        "SELECT s.assessment_id, s.stage_key, t.status AS task_status, t.error AS task_error "
        "FROM marketing_assessment_stages s JOIN tasks t ON t.id=s.task_id WHERE s.task_id=%s",
        (child_task_id,),
    )
    row = _as_dict(cur.fetchone())
    if not row:
        return None
    assessment_id = row["assessment_id"]
    if row.get("stage_key") == SYNTHESIS_STAGE and row.get("task_status") in FAILED_TASK_STATUSES:
        error = (row.get("task_error") or "strategy synthesis did not produce a validated report")[:500]
        validation = {"valid": False, "schema_version": ASSESSMENT_SCHEMA_VERSION,
                      "error": error, "generator": "deterministic"}
        cur.execute(
            "UPDATE marketing_assessments SET status='failed', validation=%s, completed_at=now(), updated_at=now() "
            "WHERE id=%s",
            (json.dumps(validation), assessment_id),
        )
        cur.execute(
            "UPDATE tasks SET status='failed', error=%s, progress=100, progress_text='strategy synthesis failed; operator review required', "
            "finished_at=now() WHERE id=(SELECT trigger_task_id FROM marketing_assessments WHERE id=%s)",
            (error, assessment_id),
        )
        return {"assessment_id": assessment_id, "status": "failed", "manifest": {}, "progress_text": error}
    reconciled = reconcile_assessment(cur, assessment_id)
    if reconciled and reconciled.get("manifest", {}).get("synthesis_eligible"):
        synthesis_task_id = queue_synthesis_if_eligible(cur, assessment_id)
        if synthesis_task_id:
            reconciled["synthesis_task_id"] = synthesis_task_id
    return reconciled


def queue_synthesis_if_eligible(cur, assessment_id):
    """Queue one deterministic synthesis task after all required sources settle.

    The status claim and task insert share the worker transaction. If a worker
    dies, both roll back, so a restart can safely reconcile and queue again.
    """
    cur.execute(
        "SELECT id, brand_id, project_id, trigger_task_id, status, source_manifest "
        "FROM marketing_assessments WHERE id=%s FOR UPDATE",
        (assessment_id,),
    )
    assessment = _as_dict(cur.fetchone())
    if not assessment or assessment.get("status") != "collecting":
        return None
    manifest = assessment.get("source_manifest") or {}
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except json.JSONDecodeError:
            manifest = {}
    if not manifest.get("synthesis_eligible"):
        return None
    cur.execute(
        "SELECT task_id FROM marketing_assessment_stages "
        "WHERE assessment_id=%s AND stage_key=%s FOR UPDATE",
        (assessment_id, SYNTHESIS_STAGE),
    )
    existing = _as_dict(cur.fetchone())
    if existing:
        return existing["task_id"]
    cur.execute(
        "UPDATE marketing_assessments SET status='synthesizing', updated_at=now() "
        "WHERE id=%s AND status='collecting' AND source_manifest->>'synthesis_eligible'='true'",
        (assessment_id,),
    )
    if cur.rowcount != 1:
        return None
    payload = json.dumps({"assessment_id": assessment_id, "brand_id": assessment["brand_id"],
                          "project_id": assessment["project_id"]})
    cur.execute(
        "INSERT INTO tasks (type, status, params, triggered_by, parent_task_id) "
        "VALUES (%s,'queued',%s,'marketing-assessment',%s) RETURNING id",
        (SYNTHESIS_STAGE, payload, assessment["trigger_task_id"]),
    )
    task = _as_dict(cur.fetchone())
    if not task or not task.get("id"):
        raise RuntimeError("marketing assessment synthesis task did not return an id")
    cur.execute(
        "INSERT INTO marketing_assessment_stages (assessment_id, stage_key, task_id, required, status) "
        "VALUES (%s,%s,%s,false,'queued')",
        (assessment_id, SYNTHESIS_STAGE, task["id"]),
    )
    return task["id"]


def claim_synthesis(cur, assessment_id):
    """Atomically reserve a fully settled collection run for one future synthesizer.

    Batch 3 calls this before spending model tokens. It is intentionally separate
    from reconciliation so this foundation never starts a model task itself.
    """
    reconciled = reconcile_assessment(cur, assessment_id)
    if not reconciled:
        return False, "assessment not found"
    if not reconciled["manifest"]["synthesis_eligible"]:
        return False, "required child stages have not settled successfully"
    cur.execute(
        "UPDATE marketing_assessments SET status='synthesizing', updated_at=now() "
        "WHERE id=%s AND status='collecting' AND source_manifest->>'synthesis_eligible'='true'",
        (assessment_id,),
    )
    return cur.rowcount == 1, "claimed" if cur.rowcount == 1 else "already claimed"


def reconcile_open_assessments(cur, limit=100):
    """Restart recovery for completed children whose final callback was interrupted."""
    cur.execute(
        "SELECT id FROM marketing_assessments WHERE status IN ('queued','collecting','synthesizing') "
        "ORDER BY id LIMIT %s",
        (limit,),
    )
    recovered = []
    for row in cur.fetchall():
        assessment_id = row["id"]
        reconciled = reconcile_assessment(cur, assessment_id)
        if reconciled and reconciled.get("manifest", {}).get("synthesis_eligible"):
            synthesis_task_id = queue_synthesis_if_eligible(cur, assessment_id)
            if synthesis_task_id:
                reconciled["synthesis_task_id"] = synthesis_task_id
        recovered.append(reconciled)
    return recovered
