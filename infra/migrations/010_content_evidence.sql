BEGIN;

ALTER TABLE content_research
  ADD COLUMN IF NOT EXISTS facts jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMIT;
