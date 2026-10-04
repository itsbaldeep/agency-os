BEGIN;
CREATE TABLE IF NOT EXISTS marketing_measurement_schedules (
 brand_id integer PRIMARY KEY REFERENCES brands(id) ON DELETE RESTRICT,
 enabled boolean NOT NULL DEFAULT false,
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- Preserve the previously authorized daily pilot. This is migration data,
-- never a brand assumption in the generic scheduler or worker.
INSERT INTO marketing_measurement_schedules(brand_id,enabled)
SELECT id,true FROM brands WHERE id=31 ON CONFLICT(brand_id) DO NOTHING;
COMMIT;
