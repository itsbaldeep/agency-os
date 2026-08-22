BEGIN;

UPDATE projects SET local_path='/home/agency/engagements/hearth' WHERE id=4;
UPDATE projects SET local_path='/home/agency/engagements/streamwise' WHERE id=5;
UPDATE projects SET local_path='/home/agency/core/deployden' WHERE id=10;
UPDATE projects SET local_path='/home/agency/core/agency-os', repo_name='agency-os' WHERE id=14;
UPDATE projects SET local_path='/home/agency/core/agency-dashboard', repo_name='agency-dashboard' WHERE id=15;

UPDATE background_jobs
SET name=CASE id
      WHEN 8 THEN 'retired-deploy-agency-os'
      WHEN 9 THEN 'retired-deploy-agency-dashboard'
      WHEN 10 THEN 'retired-self-review'
      WHEN 11 THEN 'retired-auto-merge'
    END,
    script_path='/usr/bin/false', schedule='retired', enabled=false, updated_at=now()
WHERE id BETWEEN 8 AND 11;

COMMIT;
