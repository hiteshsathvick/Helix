-- The app/worker containers must NOT connect as the migration-owning
-- superuser: Postgres superusers (and table owners without FORCE, and even
-- WITH force for superusers) always bypass Row-Level Security, which would
-- silently defeat tenant isolation. This role is the one Helix's runtime
-- code actually connects as.
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'helix_app') THEN
      CREATE ROLE helix_app LOGIN PASSWORD 'helix_app';
   END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO helix_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO helix_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO helix_app;
