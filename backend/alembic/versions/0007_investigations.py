"""Saved investigations: a completed run that someone chose to keep, with a title."""

from alembic import op

from app.rls import enable_rls

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE investigations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            run_id uuid NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
            title text NOT NULL,
            pinned boolean NOT NULL DEFAULT false,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX investigations_org_idx ON investigations (org_id, pinned DESC, created_at DESC)")
    op.execute("CREATE INDEX investigations_title_trgm ON investigations USING gin (title gin_trgm_ops)")
    enable_rls("investigations")


def downgrade() -> None:
    op.execute("DROP TABLE investigations")
