#!/usr/bin/env python3
"""Explicit, hash-bound repair of an owned private Ghost draft after renderer fixes."""
import argparse
import hashlib
import json
import worker
import ghost_publisher as ghost
from publication_settings import project_destination, destination_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-task', type=int, required=True)
    parser.add_argument('--expected-html-sha256', required=True)
    args = parser.parse_args()
    conn = worker.get_conn()
    cur = conn.cursor(cursor_factory=worker.psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM tasks WHERE id=%s AND type='publish_content' AND status='failed'", (args.failed_task,))
    task = cur.fetchone()
    if not task:
        raise RuntimeError('The named failed publication task is required')
    params = task['params']
    cur.execute('SELECT ci.*,p.local_path,b.project_id FROM content_items ci JOIN brands b ON b.id=ci.brand_id '
                "JOIN projects p ON p.id=b.project_id WHERE ci.id=%s AND p.lifecycle='active'", (params['content_item_id'],))
    item = cur.fetchone()
    if not item or item['status'] != 'publish_failed' or item['publish_task_id'] != task['id']:
        raise RuntimeError('Content no longer matches the failed task')
    config = project_destination(item['project_id'])
    if (ghost.content_digest(item) != params.get('approved_digest') or
            destination_digest(config) != params.get('approved_destination')):
        raise RuntimeError('Content or destination changed after approval')
    api = ghost.GhostAdminClient(ghost._endpoint(config), ghost._read_credential(item, config), admin_host=config.get('admin_host'))
    post = api.request('GET', f'/ghost/api/admin/posts/slug/content-{item["id"]}/?formats=html')['posts'][0]
    marker = f'#agency-content-{item["id"]}-{params["approved_digest"][:16]}'
    if (post['status'] != 'draft' or post['title'] != item['title'] or
            marker not in [t['name'] for t in post.get('tags', [])] or
            hashlib.sha256(post['html'].encode()).hexdigest() != args.expected_html_sha256):
        raise RuntimeError('Private Ghost draft does not match the inspected repair target')
    ghost._validate_item(item)
    rendered = ghost.render_pipeline_html(item)
    ghost._validate_markup(rendered)
    cur.execute("INSERT INTO tasks(type,status,params,triggered_by,started_at,result_ref) VALUES "
                "('ghost_draft_repair','running',%s,'operator-approved-repair',now(),%s) RETURNING id",
                (json.dumps({'content_item_id': item['id'], 'failed_task': task['id'], 'expected_html_sha256': args.expected_html_sha256}),
                 json.dumps({'post_id': post['id'], 'before_html': post['html'], 'before_updated_at': post['updated_at']})))
    repair_id = cur.fetchone()['id']
    conn.commit()
    try:
        api.request('PUT', f'/ghost/api/admin/posts/{post["id"]}/?source=html', {'posts': [{
            'updated_at': post['updated_at'], 'status': 'draft', 'html': rendered}]})
        ghost.publish(item, config, params['approved_digest'], publish=False, client=api)
        cur.execute("UPDATE tasks SET status='done',finished_at=now(),progress=100,progress_text='Private draft repaired and verified; not published' WHERE id=%s", (repair_id,))
        conn.commit()
        print(json.dumps({'repair_task': repair_id, 'verified': True, 'published': False, 'post_id': post['id']}))
    except Exception:
        cur.execute("UPDATE tasks SET status='failed',finished_at=now(),error='Private draft repair needs inspection; no publication attempted' WHERE id=%s", (repair_id,))
        conn.commit()
        raise RuntimeError('Private repair failed; inspect its tracked task before retry') from None
    finally:
        conn.close()


if __name__ == '__main__':
    main()
