"""Checks the superuser-only hardening (infra/postgres/hardening.sql) is in place; changes nothing itself.

The migration owner cannot apply these settings: PostgreSQL ignores REVOKE on catalog objects it does not own and
refuses ALTER ROLE without CREATEROLE. init.sh applies the file when it creates a database. Any other database
must have it applied by a superuser before this migration will run.
"""

from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"

SET_CONFIG = "pg_catalog.set_config(text, text, boolean)"
CATALOG_VIEWS = (
    "pg_catalog.pg_stat_activity",
    "pg_catalog.pg_stat_all_tables",
    "pg_catalog.pg_stat_user_tables",
    "pg_catalog.pg_stat_sys_tables",
    "pg_catalog.pg_roles",
    "pg_catalog.pg_user",
)
AGENT_ROLE_SETTINGS = {"default_transaction_read_only=on", "statement_timeout=15s"}


def hardening_gaps(conn) -> list[str]:
    """What is missing from the superuser hardening. An empty list means it is in place."""
    gaps = []

    if conn.execute(text("SELECT has_function_privilege('finops_ro', :f, 'EXECUTE')"), {"f": SET_CONFIG}).scalar():
        gaps.append("finops_ro may call set_config")
    if not conn.execute(text("SELECT has_function_privilege('finops_app', :f, 'EXECUTE')"), {"f": SET_CONFIG}).scalar():
        gaps.append("finops_app may not call set_config")
    for view in CATALOG_VIEWS:
        if conn.execute(text("SELECT has_table_privilege('finops_ro', :v, 'SELECT')"), {"v": view}).scalar():
            gaps.append(f"finops_ro may read {view}")
        if not conn.execute(text("SELECT has_table_privilege('finops_app', :v, 'SELECT')"), {"v": view}).scalar():
            gaps.append(f"finops_app may not read {view}")
    config = conn.execute(text("SELECT rolconfig FROM pg_roles WHERE rolname = 'finops_ro'")).scalar()
    missing = AGENT_ROLE_SETTINGS - set(config or [])
    if missing:
        gaps.append("finops_ro lacks role settings " + ", ".join(sorted(missing)))
    return gaps


def upgrade() -> None:
    gaps = hardening_gaps(op.get_bind())
    if gaps:
        raise RuntimeError(
            "This database lacks settings only a superuser can apply: " + "; ".join(gaps) + ". Apply "
            "infra/postgres/hardening.sql as a superuser (its header says how), then run the migrations again."
        )


def downgrade() -> None:
    pass  # nothing was changed here
