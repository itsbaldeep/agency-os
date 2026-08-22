BEGIN;

UPDATE background_jobs SET schedule='*/15 * * * *', updated_at=now() WHERE id=1;
UPDATE background_jobs
SET name='retired-approval-poller', script_path='/usr/bin/false',
    schedule='retired', enabled=false, updated_at=now()
WHERE id=2;
UPDATE background_jobs SET schedule='*/5 * * * *', updated_at=now() WHERE id=3;

COMMIT;
