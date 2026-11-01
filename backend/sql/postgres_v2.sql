-- Pin the approved base at run creation so a later rollback cannot silently
-- change the meaning of an in-flight iteration.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_mode TEXT NOT NULL DEFAULT 'create';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS base_version_id TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS base_spec_json TEXT;
INSERT INTO myatom_schema_version(version) VALUES (2) ON CONFLICT DO NOTHING;
