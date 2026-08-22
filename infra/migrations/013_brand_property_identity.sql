BEGIN;

-- brand_properties describes the latest known brand state. Preserve the
-- newest row and keep historical findings in audits/audit_results instead of
-- accumulating ambiguous current values here.
DELETE FROM brand_properties old
USING brand_properties newest
WHERE old.brand_id = newest.brand_id
  AND old.property_type = newest.property_type
  AND old.id < newest.id;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'brand_properties_brand_type_key'
      AND conrelid = 'brand_properties'::regclass
  ) THEN
    ALTER TABLE brand_properties
      ADD CONSTRAINT brand_properties_brand_type_key
      UNIQUE (brand_id, property_type);
  END IF;
END $$;

COMMIT;
