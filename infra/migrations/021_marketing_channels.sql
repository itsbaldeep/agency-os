BEGIN;
CREATE TABLE IF NOT EXISTS marketing_channels (
 brand_id integer NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
 channel text NOT NULL CHECK(channel IN ('blog','help','instagram','youtube','linkedin','facebook','x','email')),
 profile_url text NOT NULL DEFAULT '',
 handle text NOT NULL DEFAULT '',
 display_name text NOT NULL DEFAULT '',
 bio text NOT NULL DEFAULT '',
 setup_checks jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(setup_checks)='object'),
 connection_state text NOT NULL DEFAULT 'not_connected' CHECK(connection_state IN ('not_connected','owner_setup','configured')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(brand_id,channel)
);
COMMIT;
