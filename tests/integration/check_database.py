"""Read-only connection/schema probe. Never print URLs, credentials, or user rows."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.database import get_engine
from sqlalchemy import text

EXPECTED = [
    "compliance_runs",
    "execution_attempts",
    "outbox_events",
    "quarantine_records",
    "canonical_provisions",
    "feedback_records",
]


async def main():
    engine = None
    try:
        engine = get_engine()
        async with asyncio.timeout(15):
            async with engine.connect() as connection:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(text("SELECT 1"))
                names = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = current_schema()"
                            )
                        )
                    ).scalars()
                )
                revision = (
                    (await connection.execute(text("SELECT version_num FROM alembic_version")))
                    .scalars()
                    .all()
                    if "alembic_version" in names
                    else []
                )
                report = {
                    "connection": "passed",
                    "read_only": True,
                    "expected_tables_present": [name for name in EXPECTED if name in names],
                    "expected_tables_missing": [name for name in EXPECTED if name not in names],
                    "migration_revisions": revision,
                    "other_tables_present": bool(names - set(EXPECTED) - {"alembic_version"}),
                }
                print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        cause = getattr(exc, "orig", exc)
        print(
            json.dumps(
                {
                    "connection": "failed",
                    "error_type": type(cause).__name__,
                    "sqlstate": getattr(cause, "sqlstate", None),
                    "details": "Connection details and credentials redacted.",
                }
            )
        )
        return 1
    finally:
        if engine is not None:
            await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
