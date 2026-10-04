"""Brand-scoped, approval-bound recovery for static publications."""
from __future__ import annotations

import json
from typing import Callable
import psycopg2.extras

from publication_settings import destination_digest, project_destination
from static_publisher import StaticPublishError, rollback


def _fail(message: str) -> dict:
    return {"ok": False, "status": "failed", "error": message,
            "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}


def _int(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def handle(task: dict, get_conn: Callable) -> dict:
    """Rollback one approved static publication, preserving its origin task."""
    params = task.get("params") if isinstance(task, dict) else {}
    params = params if isinstance(params, dict) else {}
    brand_id = _int(params.get("brand_id"))
    content_id = _int(params.get("content_item_id"))
    publish_task_id = _int(params.get("publish_task_id"))
    manifest_hash = params.get("manifest_hash")
    approved_destination = params.get("approved_destination")
    recovery_task_id = _int(task.get("id")) if isinstance(task, dict) else None
    if not all((brand_id, content_id, publish_task_id, recovery_task_id)):
        return _fail("publication recovery requires brand, content, publish task and recovery task IDs")
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        return _fail("publication recovery manifest is invalid")
    if not isinstance(approved_destination, str) or len(approved_destination) != 64:
        return _fail("publication recovery destination approval is invalid")

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT ci.id,ci.brand_id,ci.status,ci.publish_task_id,ci.structured,b.project_id,p.lifecycle "
            "FROM content_items ci JOIN brands b ON b.id=ci.brand_id "
            "LEFT JOIN projects p ON p.id=b.project_id "
            "WHERE ci.id=%s AND ci.brand_id=%s FOR UPDATE OF ci",
            (content_id, brand_id),
        )
        item = cur.fetchone()
        if not item or item.get("brand_id") != brand_id:
            return _fail("publication recovery content is not owned by this brand")
        if item.get("status") != "published" or item.get("publish_task_id") != publish_task_id:
            return _fail("publication recovery requires the original published content task")
        if item.get("lifecycle") != "active":
            return _fail("publication recovery requires an active project")

        cur.execute(
            "SELECT id,type,status,params,result_ref FROM tasks "
            "WHERE id=%s AND type='publish_content' FOR UPDATE",
            (publish_task_id,),
        )
        origin = cur.fetchone()
        origin_params = _object(origin.get("params")) if origin else {}
        origin_result = _object(origin.get("result_ref")) if origin else {}
        if not origin or origin.get("status") != "done":
            return _fail("original publication task is not completed")
        if _int(origin_params.get("content_item_id")) != content_id or ("brand_id" in origin_params and _int(origin_params.get("brand_id")) != brand_id):
            return _fail("original publication task is not brand-scoped")
        if origin_params.get("approved_destination") != approved_destination:
            return _fail("publication destination approval does not match the original task")
        if origin_result.get("manifest_hash") != manifest_hash:
            return _fail("publication receipt does not match the requested manifest")
        if _int(origin_result.get("brand_id")) != brand_id or _int(origin_result.get("content_id")) != content_id:
            return _fail("publication receipt is not owned by this brand and content item")

        destination = project_destination(item.get("project_id"))
        if destination.get("type") != "static" or destination.get("enabled") is not True:
            return _fail("publication destination is not an enabled static brand destination")
        if destination_digest(destination) != approved_destination:
            return _fail("publication destination changed since approval")
        if str(destination.get("output_root", "")).rstrip("/").split("/")[-1] != str(brand_id):
            return _fail("publication destination is not brand-scoped")

        try:
            receipt = rollback(destination, manifest_hash)
        except (StaticPublishError, OSError, ValueError):
            return _fail("static publication recovery could not verify or remove the owned publication")

        structured = _object(item.get("structured"))
        structured["publication_rollback"] = {
            "task_id": recovery_task_id,
            "publish_task_id": publish_task_id,
            "manifest_hash": manifest_hash,
            "receipt": receipt,
        }
        cur.execute(
            "UPDATE content_items SET status='draft',structured=%s,updated_at=now() "
            "WHERE id=%s AND brand_id=%s AND status='published' AND publish_task_id=%s",
            (json.dumps(structured, sort_keys=True), content_id, brand_id, publish_task_id),
        )
        conn.commit()
        return {"ok": True, "status": "done", "workflow_status": "rolled_back",
                "brand_id": brand_id, "content_item_id": content_id,
                "publish_task_id": publish_task_id, "manifest_hash": manifest_hash,
                "content": json.dumps(receipt, sort_keys=True),
                "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return _fail("publication recovery database update failed; retry the same recovery task")
    finally:
        conn.close()
