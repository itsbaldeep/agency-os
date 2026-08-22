BEGIN;

-- Repeated black-box audits must update one competitor identity rather than
-- accumulating visually identical rows. The pre-migration duplicates have no
-- retained competitor_pages children in the audited estate.
DELETE FROM competitors c
USING competitors keep
WHERE c.brand_id = keep.brand_id
  AND lower(c.domain) = lower(keep.domain)
  AND c.id > keep.id;

CREATE UNIQUE INDEX IF NOT EXISTS competitors_brand_domain_uidx
  ON competitors (brand_id, lower(domain));

-- Every new task-originated model charge is traceable to the run that caused
-- it. job_run_id is available to scheduled scripts that later gain LLM work.
ALTER TABLE token_usage
  ADD COLUMN IF NOT EXISTS task_id integer REFERENCES tasks(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS job_run_id integer REFERENCES job_runs(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS token_usage_task_id_uidx
  ON token_usage (task_id) WHERE task_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS token_usage_job_run_id_uidx
  ON token_usage (job_run_id) WHERE job_run_id IS NOT NULL;

COMMIT;
