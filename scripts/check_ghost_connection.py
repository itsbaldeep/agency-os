#!/usr/bin/env python3
"""Run the bounded private-draft connection proof as a dashboard-visible task."""
import argparse
import json
import worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True, type=int)
    args = parser.parse_args()
    params = {'project_id': args.project_id}
    conn = worker.get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks(type,status,params,triggered_by,started_at) VALUES"
                "('ghost_connection_check','running',%s,'operator-connection-check',now()) RETURNING id", (json.dumps(params),))
    task_id = cur.fetchone()[0]
    conn.commit()
    try:
        result = worker.handle_ghost_connection_check({'id': task_id, 'params': params})
    except Exception:
        result = {'ok': False, 'error': 'Private Ghost connection check failed; no credential data was logged.'}
    cur.execute("UPDATE tasks SET status=%s,result_ref=%s,error=%s,finished_at=now(),progress=100 WHERE id=%s",
                ('done' if result.get('ok') else 'failed', result.get('content'), result.get('error'), task_id))
    conn.commit()
    conn.close()
    print(json.dumps({'task_id': task_id, 'ok': result.get('ok'), 'error': result.get('error')}))


if __name__ == '__main__':
    main()
