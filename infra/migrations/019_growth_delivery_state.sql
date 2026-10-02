BEGIN;
ALTER TABLE seo_cleanup_batches DROP CONSTRAINT IF EXISTS seo_cleanup_batches_status_check;
ALTER TABLE seo_cleanup_batches ADD CONSTRAINT seo_cleanup_batches_status_check
  CHECK (status IN ('proposed','approved','running','verified','partial','failed','cancelled'));
ALTER TABLE seo_cleanup_items DROP CONSTRAINT IF EXISTS seo_cleanup_items_status_check;
ALTER TABLE seo_cleanup_items ADD CONSTRAINT seo_cleanup_items_status_check
  CHECK (status IN ('proposed','approved','applied','verified','partial','needs_review','stale','failed','rejected'));
ALTER TABLE seo_cleanup_notifications
  ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
COMMIT;
