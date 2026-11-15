#!/bin/sh
# Creates the three database roles and both databases. Runs once, on an empty data directory.
#   finops_owner  owns the schema; used only for migrations and seeding reference data
#   finops_app    API and workers; not a table owner, so row-level security always applies
#   finops_ro     the agent's SQL tool; SELECT on schema "analytics" and nothing else
# The privileges only a superuser can set are in hardening.sql, which the migration checks for.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<SQL
CREATE ROLE finops_owner LOGIN PASSWORD '${FINOPS_OWNER_PASSWORD:-finops_owner}';
CREATE ROLE finops_app   LOGIN PASSWORD '${FINOPS_APP_PASSWORD:-finops_app}';
CREATE ROLE finops_ro    LOGIN PASSWORD '${FINOPS_RO_PASSWORD:-finops_ro}';
CREATE DATABASE finops      OWNER finops_owner;
CREATE DATABASE finops_test OWNER finops_owner;
SQL
for db in finops finops_test; do
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$db" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO finops_app;
CREATE SCHEMA analytics AUTHORIZATION finops_owner;
GRANT USAGE ON SCHEMA analytics TO finops_app, finops_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE finops_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO finops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE finops_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO finops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE finops_owner IN SCHEMA analytics
  GRANT SELECT ON TABLES TO finops_app, finops_ro;
SQL
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$db" -f /opt/finops/hardening.sql
done
