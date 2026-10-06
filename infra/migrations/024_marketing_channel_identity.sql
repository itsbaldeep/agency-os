BEGIN;

ALTER TABLE marketing_channels
    ADD COLUMN IF NOT EXISTS identity_assets jsonb NOT NULL DEFAULT '{}';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'marketing_channels'::regclass
          AND conname = 'marketing_channels_identity_assets_object'
    ) THEN
        ALTER TABLE marketing_channels
            ADD CONSTRAINT marketing_channels_identity_assets_object
            CHECK (jsonb_typeof(identity_assets) = 'object');
    END IF;
END
$$;

COMMIT;
