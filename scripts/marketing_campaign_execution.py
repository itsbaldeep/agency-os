"""Core ledger workflow for approved brand-owned campaign dispatches.

This module never stores recipients or calls a provider.  The source adapter
owns both and is reached only after a durable dispatching claim.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import marketing_campaign_adapter as adapter
import psycopg2.extras

TERMINAL = {"accepted", "delivered", "partial", "blocked", "cancelled"}
RECONCILE_ONLY = {"dispatching", "uncertain"}


def _params(task: dict[str, Any]) -> dict[str, Any]:
    value = task.get("params") if isinstance(task, dict) else None
    if isinstance(value, str):
        try: value = json.loads(value)
        except (TypeError, ValueError): raise ValueError("invalid campaign parameters")
    if not isinstance(value, dict):
        raise ValueError("invalid campaign parameters")
    return value


def _ids(params: dict[str, Any], names: tuple[str, ...]) -> dict[str, int]:
    if set(params) != set(names):
        raise ValueError("invalid campaign parameters")
    result: dict[str, int] = {}
    for name in names:
        value = params[name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("invalid campaign parameters")
        result[name] = value
    return result


def _config(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return adapter.validate_config(value)


def _cursor(conn: Any) -> Any:
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _row(cur: Any, brand_id: int, item_id: int, *, lock: bool = True) -> Any:
    suffix = " FOR UPDATE OF wi" if lock else ""
    cur.execute("""SELECT wi.*, b.id AS locked_brand_id, p.lifecycle AS brand_lifecycle,
        p.classification, p.local_path, bp.value AS adapter_config
        FROM marketing_work_items wi JOIN brands b ON b.id=wi.brand_id
        JOIN projects p ON p.id=b.project_id
        LEFT JOIN brand_properties bp ON bp.brand_id=b.id AND bp.property_type='campaign_adapter_config'
        WHERE wi.brand_id=%s AND wi.id=%s""" + suffix, (brand_id, item_id))
    return cur.fetchone()


def _safe_result(status: str, *, receipt: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": status not in {"blocked", "uncertain"}, "status": status}
    if receipt is not None:
        result["receipt"] = receipt
        result["content"] = json.dumps(receipt, sort_keys=True)
    if error:
        result["error"] = error
    return result


def handle_preview(task: dict[str, Any], get_conn: Any, client: Any = adapter) -> dict[str, Any]:
    try: params = _ids(_params(task), ("brand_id", "item_id", "revision"))
    except ValueError: return _safe_result("blocked", error="invalid campaign parameters")
    conn = get_conn()
    try:
        cur = _cursor(conn)
        row = _row(cur, params["brand_id"], params["item_id"])
        if not row or row["brand_id"] != params["brand_id"] or row["revision"] != params["revision"]:
            conn.rollback(); return _safe_result("blocked", error="campaign draft is stale or unavailable")
        if row["state"] not in {"draft", "ready"} or row["brand_lifecycle"] != "active" or row.get("classification") not in {"core", "engagement"}:
            conn.rollback(); return _safe_result("blocked", error="campaign draft is not available")
        config = _config(row["adapter_config"])
        project = {"classification": row.get("classification"), "local_path": row.get("local_path")}
        item = dict(row)
        if item.get('planned_at'):
            item['planned_at'] = item['planned_at'].isoformat()
        result = client.request_preview(item, config, project, datetime.now(UTC))
        result = adapter._validate_preview(result, datetime.now(UTC))
        expected = adapter.preview_request(item, datetime.now(UTC))
        if any(result[key] != expected[key] for key in ('schema_version','brand_id','item_id','revision','message_digest','policy_digest')):
            raise ValueError('campaign preview identity changed')
        brief = row.get("brief") or {}
        if isinstance(brief, str): brief = json.loads(brief)
        brief = {**brief, "campaign_preview": result}
        cur.execute("UPDATE marketing_work_items SET brief=%s::jsonb, updated_at=now() WHERE id=%s AND revision=%s", (json.dumps(brief, sort_keys=True), params["item_id"], params["revision"]))
        conn.commit()
        return {"ok": True, "status": "previewed", "content": json.dumps(result, sort_keys=True)}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return _safe_result("blocked", error="campaign preview could not be recorded")
    finally:
        conn.close()


def _load_run(cur: Any, run_id: int, brand_id: int) -> Any:
    cur.execute("""SELECT wi.*, b.id AS item_brand_id, p.lifecycle AS brand_lifecycle,
        p.classification, p.local_path, bp.value AS adapter_config
        FROM marketing_campaign_runs r JOIN marketing_work_items wi ON wi.id=r.item_id
        JOIN brands b ON b.id=wi.brand_id JOIN projects p ON p.id=b.project_id
        LEFT JOIN brand_properties bp ON bp.brand_id=b.id AND bp.property_type='campaign_adapter_config'
        WHERE r.id=%s AND r.brand_id=%s FOR UPDATE OF wi""", (run_id, brand_id))
    item = cur.fetchone()
    if not item: return None
    cur.execute("SELECT * FROM marketing_campaign_runs WHERE id=%s AND brand_id=%s FOR UPDATE", (run_id, brand_id))
    run = cur.fetchone()
    if not run: return None
    return {**item, **run, "item_brand_id": item["item_brand_id"], "item_revision": item["revision"], "item_state": item["state"], "brand_lifecycle": item["brand_lifecycle"], "classification": item["classification"], "local_path": item["local_path"], "adapter_config": item["adapter_config"]}


def handle_dispatch(task: dict[str, Any], get_conn: Any, client: Any = adapter) -> dict[str, Any]:
    try: params = _ids(_params(task), ("run_id", "brand_id"))
    except ValueError: return _safe_result("blocked", error="invalid campaign parameters")
    conn = get_conn()
    claimed = False
    try:
        cur = _cursor(conn)
        row = _load_run(cur, params["run_id"], params["brand_id"])
        if not row or row["brand_lifecycle"] != "active" or row.get("classification") not in {"core", "engagement"} or row["item_brand_id"] != params["brand_id"] or row["item_revision"] != row["revision"] or row["item_state"] != "ready":
            if row and row.get('state') == 'queued':
                cur.execute("UPDATE marketing_campaign_runs SET state='blocked',error='campaign draft is stale or unavailable',updated_at=now() WHERE id=%s AND brand_id=%s AND state='queued'", (params['run_id'], params['brand_id']))
                conn.commit()
            else:
                conn.rollback()
            return _safe_result("blocked", error="campaign run is stale or unavailable")
        state = row["state"]
        if state in TERMINAL: conn.rollback(); return _safe_result(state, receipt=row.get("receipt"), error="campaign run is already terminal")
        if state in RECONCILE_ONLY: conn.rollback(); return _safe_result("uncertain", error="campaign run requires receipt reconciliation")
        if state != "queued":
            conn.rollback(); return _safe_result("blocked", error="campaign run is not queued")
        config = _config(row["adapter_config"])
        contract = row["contract"] if isinstance(row["contract"], dict) else json.loads(row["contract"])
        now = datetime.now(UTC)
        adapter.validate_contract(contract, config, now)
        if contract.get("brand_id") != row["brand_id"] or contract.get("item_id") != row["item_id"] or contract.get("revision") != row["revision"] or contract.get("approval_digest") != row["approval_digest"] or contract.get("idempotency_key") != row["idempotency_key"]:
            raise ValueError("campaign contract is stale")
        row_send = row["send_at"].astimezone(UTC) if hasattr(row["send_at"], "astimezone") else datetime.fromisoformat(str(row["send_at"]).replace("Z", "+00:00")).astimezone(UTC)
        contract_send = datetime.fromisoformat(contract["send_at"].replace("Z", "+00:00")).astimezone(UTC)
        if row_send != contract_send:
            raise ValueError("campaign delivery time is stale")
        if row_send > now:
            conn.rollback(); return _safe_result("blocked", error="campaign run is not due")
        if task.get("id") is not None and task.get("id") != row.get("task_id"):
            raise ValueError('campaign task ownership is stale')
        cur.execute("UPDATE marketing_campaign_runs SET state='dispatching', updated_at=now() WHERE id=%s AND state='queued'", (params["run_id"],))
        conn.commit()
        claimed = True
        project = {"classification": row.get("classification"), "local_path": row.get("local_path")}
        try:
            result = client.request_dispatch(contract, config, project)
            if not isinstance(result, dict):
                raise ValueError("invalid source result")
            status = result.get("status")
            if status != "uncertain":
                result = adapter.validate_receipt(result, contract)
        except Exception:
            result = {"status": "uncertain", "error": "source_unavailable"}
        status = result.get("status") if isinstance(result, dict) else "uncertain"
        if status not in {"accepted", "delivered", "partial", "blocked", "uncertain"}:
            status = "uncertain"
        receipt = result if isinstance(result, dict) and status != "uncertain" else None
        safe_error = 'source outcome requires receipt reconciliation' if status == 'uncertain' else 'source blocked this delivery' if status == 'blocked' else None
        conn2 = get_conn()
        try:
            cur2 = _cursor(conn2)
            cur2.execute("UPDATE marketing_campaign_runs SET state=%s, receipt=%s, error=%s, updated_at=now() WHERE id=%s AND state='dispatching'", (status, json.dumps(receipt, sort_keys=True) if receipt else None, safe_error, params["run_id"]))
            conn2.commit()
        except Exception:
            try: conn2.rollback()
            except Exception: pass
            return _safe_result("uncertain", error="dispatch result requires receipt reconciliation")
        finally: conn2.close()
        return _safe_result(status, receipt=receipt, error=safe_error)
    except Exception:
        if claimed:
            return _safe_result('uncertain', error='dispatch result requires receipt reconciliation')
        try:
            conn.rollback()
            cur = _cursor(conn)
            cur.execute("UPDATE marketing_campaign_runs SET state='blocked', error=%s, updated_at=now() WHERE id=%s AND brand_id=%s AND state='queued'", ("campaign preflight failed", params["run_id"], params["brand_id"]))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        return _safe_result("blocked", error="campaign dispatch could not be started")
    finally:
        conn.close()


def handle_receipt(task: dict[str, Any], get_conn: Any, client: Any = adapter) -> dict[str, Any]:
    try: params = _ids(_params(task), ("run_id", "brand_id"))
    except ValueError: return _safe_result("blocked", error="invalid campaign parameters")
    conn = get_conn()
    try:
        cur = _cursor(conn); row = _load_run(cur, params["run_id"], params["brand_id"])
        if not row: conn.rollback(); return _safe_result("blocked", error="campaign run unavailable")
        if row["state"] not in {"dispatching", "accepted", "partial", "uncertain"}:
            conn.rollback(); return _safe_result("blocked", error="campaign run is not reconcilable")
        config = _config(row["adapter_config"]); contract = row["contract"] if isinstance(row["contract"], dict) else json.loads(row["contract"])
        adapter.validate_contract(contract, config, datetime.now(UTC), allow_expired=True)
        if row["brand_lifecycle"] != "active" or row.get("classification") not in {"core", "engagement"}:
            raise ValueError("campaign owner is unavailable")
        if any(contract.get(key) != row.get(key) for key in ("brand_id", "item_id", "revision", "approval_digest", "idempotency_key")):
            raise ValueError("campaign receipt identity is stale")
        project = {"classification": row.get("classification"), "local_path": row.get("local_path")}
        receipt = client.request_receipt(contract, config, project)
        receipt = adapter.validate_receipt(receipt, contract)
        status = receipt["status"]
        cur.execute("UPDATE marketing_campaign_runs SET state=%s, receipt=%s, error=NULL, updated_at=now() WHERE id=%s", (status, json.dumps(receipt, sort_keys=True), params["run_id"]))
        conn.commit(); return _safe_result(status, receipt=receipt)
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return _safe_result("uncertain", error="receipt reconciliation failed")
    finally: conn.close()


def enqueue_due(get_conn: Any, limit: int = 20) -> dict[str, Any]:
    conn = get_conn(); count = 0
    try:
        cur = _cursor(conn); cur.execute("SELECT id,brand_id FROM marketing_campaign_runs WHERE state='approved' AND send_at<=now() ORDER BY send_at,id FOR UPDATE SKIP LOCKED LIMIT %s", (limit,))
        for run in cur.fetchall():
            run_id, brand_id = run["id"], run["brand_id"]
            cur.execute("INSERT INTO tasks(type,status,params,triggered_by) VALUES ('marketing_campaign_dispatch','queued',%s,'campaign_scheduler') RETURNING id", (json.dumps({"run_id": run_id, "brand_id": brand_id}, sort_keys=True),))
            task_row = cur.fetchone(); task_id = task_row["id"]
            cur.execute("UPDATE marketing_campaign_runs SET state='queued',task_id=%s,updated_at=now() WHERE id=%s AND state='approved'", (task_id, run_id)); count += 1
        conn.commit(); return {"ok": True, "queued": count}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return {"ok": False, "queued": 0, "error": "campaign scheduling failed"}
    finally: conn.close()


def cancel(run_id: int, brand_id: int, get_conn: Any) -> dict[str, Any]:
    conn = get_conn()
    try:
        cur = conn.cursor(); cur.execute("UPDATE marketing_campaign_runs SET state='cancelled',updated_at=now() WHERE id=%s AND brand_id=%s AND state IN ('approved','queued')", (run_id, brand_id)); changed = cur.rowcount; conn.commit()
        return {"ok": bool(changed), "cancelled": bool(changed)}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return {"ok": False, "error": "campaign cancellation failed"}
    finally: conn.close()
