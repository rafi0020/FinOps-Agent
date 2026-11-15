-- Privileges and role settings that only a superuser can change. Idempotent.
--
--   init.sh runs this on the finops and finops_test databases when the data directory is created.
--   Any other database: run it once as a superuser before the first migration, for example
--     docker compose exec -T db psql -U postgres -d finops -v ON_ERROR_STOP=1 < infra/postgres/hardening.sql
--   The migration 0009_hardening_check verifies these settings and refuses to run without them. The migration
--   owner cannot do this itself: PostgreSQL ignores REVOKE on pg_catalog objects it does not own (with a warning)
--   and refuses ALTER ROLE without CREATEROLE.

-- The tenant is carried in a transaction-local setting. Only application roles may change settings from SQL;
-- the agent's role cannot, so a model-written query has no way to switch tenant.
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO finops_app, finops_owner;

-- Every organisation's agent queries run as finops_ro, and a role can read the query text of its own other
-- sessions in pg_stat_activity. Nothing in the application needs these views.
REVOKE SELECT ON pg_catalog.pg_stat_activity, pg_catalog.pg_stat_all_tables, pg_catalog.pg_stat_user_tables,
  pg_catalog.pg_stat_sys_tables, pg_catalog.pg_roles, pg_catalog.pg_user FROM PUBLIC;
GRANT SELECT ON pg_catalog.pg_stat_activity, pg_catalog.pg_stat_all_tables, pg_catalog.pg_stat_user_tables,
  pg_catalog.pg_stat_sys_tables, pg_catalog.pg_roles, pg_catalog.pg_user TO finops_owner, finops_app;

-- The agent's SQL role is read-only and time-limited by default. Role settings apply to every database.
ALTER ROLE finops_ro SET default_transaction_read_only = on;
ALTER ROLE finops_ro SET statement_timeout = '15s';
