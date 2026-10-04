#!/usr/bin/env python3
"""Queue one owned-brand measurement per UTC day through the dashboard workflow."""
import argparse
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

STATE = Path('/home/agency/.local/state/agency-os/growth-scheduler')
BASE = 'http://100.64.0.1:5001'


def queue(brand_id, directory=STATE, day=None, opener=urlopen):
    if not isinstance(brand_id, int) or isinstance(brand_id, bool) or brand_id <= 0:
        raise ValueError('brand_id must be a positive integer')
    today = day or datetime.now(timezone.utc).date().isoformat()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / f'{brand_id}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = directory / f'{brand_id}.json'
        prior = json.loads(receipt.read_text()) if receipt.exists() else {}
        if prior.get('day') == today:
            return {**prior, 'deduplicated_day': True}
        request = Request(f'{BASE}/api/brands/{brand_id}/seo-measurement', data=b'{}',
                          headers={'Content-Type': 'application/json', 'Origin': BASE}, method='POST')
        try:
            with opener(request, timeout=30) as response:
                result = json.loads(response.read(16384))
        except HTTPError as exc:
            # Parked engagements must not become a dependency of core schedules.
            if exc.code == 409:
                exc.close()
                return {'brand_id': brand_id, 'skipped': 'project not eligible or inactive'}
            exc.close()
            raise RuntimeError(f'Measurement enqueue returned HTTP {exc.code}') from None
        task_id = result.get('task_id')
        if result.get('ok') is not True or type(task_id) is not int or task_id <= 0:
            raise RuntimeError('Measurement enqueue returned an invalid task reference')
        record = {'brand_id': brand_id, 'day': today, 'task_id': task_id}
        temporary = directory / f'{brand_id}.json.tmp'
        with temporary.open('w') as output:
            json.dump(record, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(receipt)
        return record


def configured_brands():
    import psycopg2
    values = {}
    with open('/home/agency/.config/agency/core.env') as source:
        for line in source:
            if '=' in line and not line.startswith('#'):
                key,value=line.strip().split('=',1);values[key]=value.strip('"').strip("'")
    conn=psycopg2.connect(host='100.64.0.1',dbname='agencyos',user='agency',password=values.get('POSTGRES_PASSWORD'))
    try:
        cur=conn.cursor()
        cur.execute("""SELECT ms.brand_id FROM marketing_measurement_schedules ms
            JOIN brands b ON b.id=ms.brand_id LEFT JOIN projects p ON p.id=b.project_id
            WHERE ms.enabled AND (b.project_id IS NULL OR p.lifecycle='active') ORDER BY ms.brand_id""")
        return [row[0] for row in cur.fetchall()]
    finally:conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('brand_id', type=int, nargs='*')
    parser.add_argument('--configured', action='store_true')
    args = parser.parse_args()
    for brand_id in dict.fromkeys(configured_brands() if args.configured else args.brand_id):
        print(json.dumps(queue(brand_id)))
