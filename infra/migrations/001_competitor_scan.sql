ALTER TABLE competitors
  ADD COLUMN IF NOT EXISTS scan_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS sitemap_url text,
  ADD COLUMN IF NOT EXISTS feed_url text,
  ADD COLUMN IF NOT EXISTS path_filter text,
  ADD COLUMN IF NOT EXISTS sitemap_hash text,
  ADD COLUMN IF NOT EXISTS last_scanned_at timestamptz;


CREATE TABLE IF NOT EXISTS competitor_pages (
  id serial PRIMARY KEY,
  competitor_id integer NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
  url text NOT NULL,
  lastmod timestamptz,
  title text,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (competitor_id, url)
);
CREATE INDEX IF NOT EXISTS competitor_pages_first_seen_idx
  ON competitor_pages (competitor_id, first_seen_at DESC);
