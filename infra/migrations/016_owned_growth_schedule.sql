BEGIN;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM background_jobs WHERE id=17 AND name <> 'owned-growth-measurement') THEN
        RAISE EXCEPTION 'Background job 17 is already allocated';
    END IF;
END $$;
INSERT INTO background_jobs (id,name,script_path,schedule,enabled,requires_approval)
VALUES (17,'owned-growth-measurement','/home/agency/agency-os/scripts/owned-growth-measurement.sh','30 6 * * *',true,false)
ON CONFLICT (id) DO UPDATE SET script_path=EXCLUDED.script_path,
    schedule=EXCLUDED.schedule, enabled=true, requires_approval=false, updated_at=now();
COMMIT;
