"""Explicit corpus import: canonical Neon first, derived Chroma second.

Raw source metadata must be supplied in sources.json; dates are never inferred
from filenames or act names. Empty files and conflicting IDs fail before writes.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.compliance import CanonicalProvision
from ingestion.models import ParsedProvision
from ingestion.parser import parse_statutory_text
from retrieval.vector_store import VectorStoreManager
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from worker.guardrails.input_guard import inspect_input_guardrail

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = str(ROOT / "data/verified")
DEFAULT_JSONL_PATH = str(ROOT / "data/verified/legal_provisions.jsonl")
DEFAULT_MANIFEST_PATH = str(ROOT / "data/sources.json")


def load_provisions(
    data_dir=DEFAULT_DATA_DIR, jsonl_path=DEFAULT_JSONL_PATH, manifest_path=DEFAULT_MANIFEST_PATH
):
    items = []
    structured = Path(jsonl_path)
    if structured.is_file():
        for line in structured.read_text().splitlines():
            if line.strip():
                items.append(ParsedProvision.model_validate_json(line))
    raw = Path(data_dir)
    manifest = json.loads(Path(manifest_path).read_text()) if Path(manifest_path).is_file() else {}
    for path in sorted(raw.glob("*.txt")):
        text = path.read_text().strip()
        if not text:
            continue
        metadata = manifest.get(path.name)
        if not metadata:
            raise ValueError(
                f"Supply verified source metadata in sources.json for {path.name} before importing raw text."
            )
        items.extend(parse_statutory_text(text=text, **metadata))
    unique = {}
    for p in items:
        if (
            not p.provision_text.strip()
            or not inspect_input_guardrail(p.provision_text, max_characters=16000)[0]
        ):
            raise ValueError("Corpus contains an empty passage or unsupported instructions.")
        prior = unique.get(p.provision_id)
        if prior and prior.model_dump() != p.model_dump():
            raise ValueError(f"Conflicting definitions for provision identifier {p.provision_id}.")
        unique[p.provision_id] = p
    if not unique:
        raise ValueError(
            "No provisions found. Supply verified source data; no database or vector writes performed."
        )
    return list(unique.values())


async def run_ingestion_pipeline(
    data_dir=DEFAULT_DATA_DIR, jsonl_path=DEFAULT_JSONL_PATH, manifest_path=DEFAULT_MANIFEST_PATH
):
    provisions = load_provisions(data_dir, jsonl_path, manifest_path)
    async with async_session_maker() as db:
        records = []
        for p in provisions:
            values = p.model_dump(exclude={"page_number", "source_url", "related_provisions"})
            values.update(
                source_url=p.source_url,
                page_number=p.page_number,
                related_provisions=p.related_provisions,
                content_hash=p.compute_content_hash(),
            )
            records.append(values)
        # One database round trip per batch instead of one per provision.
        for offset in range(0, len(records), 100):
            statement = insert(CanonicalProvision).values(records[offset : offset + 100])
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[CanonicalProvision.provision_id],
                    set_={
                        k: getattr(statement.excluded, k) for k in records[0] if k != "provision_id"
                    },
                )
            )
        await db.commit()
        canonical = (await db.execute(select(CanonicalProvision))).scalars().all()
        snapshot = [
            {c.name: getattr(p, c.name) for c in CanonicalProvision.__table__.columns}
            for p in canonical
        ]
    # Failed indexing is a visible failure; rerun safely repairs the derived index.
    index = (
        await asyncio.to_thread(VectorStoreManager().upsert_provisions, snapshot)
        if settings.RETRIEVAL_MODE == "hybrid"
        else {"mode": "lexical", "indexed": 0, "details": "Workers index canonical text in memory"}
    )
    return {
        "imported_provisions": len(provisions),
        "canonical_total": len(snapshot),
        "vector_index": index,
        "idempotency": "Primary-key upsert; repeated-import acceptance must be verified separately.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--jsonl-path", default=DEFAULT_JSONL_PATH)
    parser.add_argument("--manifest-path", default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_ingestion_pipeline(**vars(args))), indent=2))
