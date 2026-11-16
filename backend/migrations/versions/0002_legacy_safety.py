"""Add safety fields and uniqueness to pre-migration deployments without deleting data."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent DDL also works when 0001 created the current schema from scratch.
    op.execute(
        "ALTER TABLE compliance_runs ADD COLUMN IF NOT EXISTS establishment_category VARCHAR(64)"
    )
    op.execute("ALTER TABLE compliance_runs ADD COLUMN IF NOT EXISTS execution_trace JSONB")
    op.execute("ALTER TABLE compliance_runs ADD COLUMN IF NOT EXISTS active_attempt_id UUID")
    op.execute("ALTER TABLE compliance_runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ")
    op.execute("ALTER TABLE canonical_provisions ADD COLUMN IF NOT EXISTS source_url TEXT")
    op.execute("ALTER TABLE canonical_provisions ADD COLUMN IF NOT EXISTS page_number VARCHAR(64)")
    op.execute("ALTER TABLE canonical_provisions ADD COLUMN IF NOT EXISTS related_provisions JSONB")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_run_client_key' AND conrelid='compliance_runs'::regclass) THEN
            IF EXISTS (SELECT 1 FROM compliance_runs WHERE idempotency_key IS NOT NULL GROUP BY client_id,idempotency_key HAVING count(*)>1) THEN
                RAISE EXCEPTION 'Existing duplicate client idempotency keys require operator reconciliation; no data removed';
            END IF;
            ALTER TABLE compliance_runs ADD CONSTRAINT uq_run_client_key UNIQUE (client_id,idempotency_key);
        END IF;
    END $$""")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; preserve existing user data.")
