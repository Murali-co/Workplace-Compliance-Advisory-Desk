"""Initial additive compliance schema; existing tables are preserved."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS canonical_provisions (\n\tprovision_id VARCHAR(64) NOT NULL, \n\tact VARCHAR(256) NOT NULL, \n\tchapter VARCHAR(256), \n\tsection VARCHAR(32) NOT NULL, \n\tsubsection VARCHAR(32), \n\tclause VARCHAR(64), \n\tprovision_type VARCHAR(64) NOT NULL, \n\tparent_provision VARCHAR(64), \n\tprovision_text TEXT NOT NULL, \n\teffective_from DATE, \n\teffective_until DATE, \n\tlegal_status VARCHAR(64) NOT NULL, \n\tnotification_ref VARCHAR(128), \n\tsource_url TEXT, \n\tpage_number VARCHAR(64), \n\trelated_provisions JSONB, \n\tsource_doc_id VARCHAR(64) NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (provision_id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS compliance_runs (\n\trun_id UUID NOT NULL, \n\tclient_id VARCHAR(128) NOT NULL, \n\tidempotency_key VARCHAR(256), \n\tpayload_hash VARCHAR(64) NOT NULL, \n\tquery_text TEXT NOT NULL, \n\tscenario_date DATE NOT NULL, \n\temployment_start_date DATE, \n\temployment_end_date DATE, \n\testablishment_size INTEGER, \n\tdomain_hint VARCHAR(64), \n\testablishment_category VARCHAR(64), \n\tstatus VARCHAR(9) NOT NULL, \n\tbusiness_route VARCHAR(24), \n\troute_reason TEXT, \n\tadvisory_text TEXT, \n\tcitations JSONB, \n\textracted_entities JSONB, \n\tclaim_digest VARCHAR(64), \n\tprompt_version VARCHAR(64), \n\texecution_trace JSONB, \n\tactive_attempt_id UUID, \n\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n\tcorrelation_id VARCHAR(128) NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (run_id), \n\tCONSTRAINT uq_run_client_key UNIQUE (client_id, idempotency_key)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_runs_idempotency_key ON compliance_runs (idempotency_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_compliance_runs_client_id ON compliance_runs (client_id)"
    )
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS outbox_events (\n\tevent_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tevent_type VARCHAR(64) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstatus VARCHAR(10) NOT NULL, \n\tretry_count INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (event_id)\n)\n\n"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_events_run_id ON outbox_events (run_id)")
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS quarantine_records (\n\tquarantine_id UUID NOT NULL, \n\tclient_id VARCHAR(128) NOT NULL, \n\tendpoint VARCHAR(256) NOT NULL, \n\treceived_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcorrelation_id VARCHAR(128) NOT NULL, \n\terror_details JSONB NOT NULL, \n\tpayload_snippet TEXT NOT NULL, \n\tPRIMARY KEY (quarantine_id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quarantine_records_client_id ON quarantine_records (client_id)"
    )
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS execution_attempts (\n\tattempt_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tworker_id VARCHAR(128) NOT NULL, \n\tattempt_number INTEGER NOT NULL, \n\tcorrelation_id VARCHAR(128) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\terror_message TEXT, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tstep_metrics JSONB, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (attempt_id), \n\tFOREIGN KEY(run_id) REFERENCES compliance_runs (run_id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE IF NOT EXISTS feedback_records (\n\tfeedback_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tclient_id VARCHAR(128) NOT NULL, \n\tsatisfactory BOOLEAN NOT NULL, \n\treason VARCHAR(1000), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (feedback_id), \n\tFOREIGN KEY(run_id) REFERENCES compliance_runs (run_id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_records_run_id ON feedback_records (run_id)")


def downgrade():
    raise RuntimeError("Destructive downgrade requires a separately reviewed data-retention plan.")
