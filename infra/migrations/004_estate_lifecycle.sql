BEGIN;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS classification text NOT NULL DEFAULT 'engagement';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS lifecycle text NOT NULL DEFAULT 'active';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS recovery_ref text;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS parked_at timestamptz;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS ops_manifest jsonb NOT NULL DEFAULT '{}'::jsonb;

DO $$ BEGIN
  ALTER TABLE projects ADD CONSTRAINT projects_classification_check
    CHECK (classification IN ('core','engagement'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE projects ADD CONSTRAINT projects_lifecycle_check
    CHECK (lifecycle IN ('active','soft_parked','hard_parked'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

UPDATE projects SET classification='core', lifecycle='active', state='live'
WHERE lower(name) IN ('dashboard','agency-os','agency-dashboard','deployden');

UPDATE projects SET classification='engagement', lifecycle='soft_parked', state='archived',
  parked_at=COALESCE(parked_at,now())
WHERE lower(name) IN ('hearth','streamwise');

UPDATE projects SET classification='engagement', lifecycle='hard_parked', state='archived',
  agent_allowed=false, parked_at=COALESCE(parked_at,now())
WHERE lower(name)='aetheria';

UPDATE projects SET classification='engagement', lifecycle='hard_parked', state='archived',
  agent_allowed=false, parked_at=COALESCE(parked_at,now())
WHERE lower(name) NOT IN (
  'dashboard','agency-os','agency-dashboard','deployden','hearth','streamwise','technoflavour'
);

UPDATE projects SET classification='engagement', lifecycle='active'
WHERE lower(name)='technoflavour';

-- Old repo-only duplicates must not own the canonical repo_name.
UPDATE projects SET repo_name=NULL, local_path=NULL, agent_allowed=false
WHERE lower(name) IN ('hearth-repo','streamwise-repo');

UPDATE projects SET repo_name='hearth', local_path='/home/agency/projects/hearth', agent_allowed=false,
  recovery_ref='/home/agency/backups/engagements/hearth/2026-08-22-pre-park',
  ops_manifest='{"containers":["hearth-api","hearth-public-api","hearth-web-customer","hearth-web-b2b","hearth-web-admin","hearth-db","hearth-redis","hearth-clickhouse","hearth-storage"]}'::jsonb
WHERE lower(name)='hearth';

UPDATE projects SET repo_name='streamwise', local_path='/home/agency/projects/streamwise', agent_allowed=false,
  recovery_ref='/home/agency/backups/engagements/streamwise/2026-08-22-pre-park',
  ops_manifest='{"containers":["streamwise-web","streamwise-admin","streamwise-blog"]}'::jsonb
WHERE lower(name)='streamwise';

UPDATE projects SET local_path=NULL, agent_allowed=false,
  recovery_ref='/home/agency/backups/engagements/aetheria/2026-08-22-hard-park',
  ops_manifest='{}'::jsonb
WHERE lower(name)='aetheria';

UPDATE projects SET local_path='/home/agency/projects/deployden', repo_name='deployden', agent_allowed=true
WHERE lower(name)='deployden';

INSERT INTO brands (name,slug,project_id,access_tier)
SELECT 'Deployden','deployden',id,'0' FROM projects WHERE lower(name)='deployden'
ON CONFLICT (slug) DO UPDATE SET project_id=EXCLUDED.project_id;

INSERT INTO brand_properties (brand_id,property_type,value,accessible)
SELECT b.id,'domain','deployden.tech',true FROM brands b WHERE b.slug='deployden'
  AND NOT EXISTS (SELECT 1 FROM brand_properties bp WHERE bp.brand_id=b.id AND bp.property_type='domain' AND bp.value='deployden.tech');

CREATE INDEX IF NOT EXISTS idx_projects_classification_lifecycle
  ON projects(classification,lifecycle);

COMMIT;
