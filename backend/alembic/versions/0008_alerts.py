"""Alert rules (created only through an approved proposal) and the events they raise."""

from alembic import op

from app.rls import enable_rls

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE alert_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            metric text NOT NULL,
            comparison text NOT NULL CHECK (comparison IN ('<', '>')),
            threshold numeric NOT NULL,
            "window" text NOT NULL CHECK ("window" IN ('month', 'quarter')),
            region text,
            rationale text NOT NULL DEFAULT '',
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
            run_id uuid REFERENCES runs(id) ON DELETE SET NULL,
            step_idx int,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (run_id, step_idx)
        )
    """)
    enable_rls("alert_rules")
    op.execute("""
        CREATE TABLE alert_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            rule_id uuid NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
            period text NOT NULL,
            value numeric NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            acknowledged_by uuid REFERENCES users(id) ON DELETE SET NULL,
            acknowledged_at timestamptz,
            UNIQUE (rule_id, period)
        )
    """)
    op.execute("CREATE INDEX alert_events_org_idx ON alert_events (org_id, created_at DESC)")
    enable_rls("alert_events")


def downgrade() -> None:
    op.execute("DROP TABLE alert_events, alert_rules")
