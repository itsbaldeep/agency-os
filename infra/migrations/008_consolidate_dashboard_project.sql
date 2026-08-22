BEGIN;

DELETE FROM projects
WHERE id=15
  AND NOT EXISTS (SELECT 1 FROM services WHERE project_id=15)
  AND NOT EXISTS (SELECT 1 FROM brands WHERE project_id=15)
  AND NOT EXISTS (SELECT 1 FROM capabilities WHERE project_id=15)
  AND NOT EXISTS (SELECT 1 FROM approvals WHERE project_id=15)
  AND NOT EXISTS (SELECT 1 FROM ports WHERE project_id=15)
  AND NOT EXISTS (SELECT 1 FROM token_usage WHERE project_id=15);

UPDATE projects
SET name='agency-dashboard', repo_name='agency-dashboard',
    local_path='/home/agency/core/agency-dashboard', classification='core',
    lifecycle='active', state='live'
WHERE id=3;

COMMIT;
