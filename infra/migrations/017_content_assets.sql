BEGIN;
CREATE TABLE IF NOT EXISTS content_assets (
    id BIGSERIAL PRIMARY KEY,
    brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
    content_item_id INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brand_id, sha256)
);
CREATE INDEX IF NOT EXISTS idx_content_assets_content ON content_assets(content_item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_assets_brand ON content_assets(brand_id, created_at DESC);
COMMIT;
