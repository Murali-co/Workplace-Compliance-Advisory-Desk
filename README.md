# Murali_backend — Workplace Compliance Advisory Desk

Backend API, persistence, execution, retrieval and ingestion. This contribution contains **43 of 86 original source-code files (50.00%)**.

## Scope

This is a contribution snapshot, not a standalone full-application checkout. Combine all three parts to obtain the full application. In particular, backend execution imports the prompt package allocated to Part 3. Frontend and local startup code are in Part 2.

Public dependency/build configuration, this README and the split manifests are support files, excluded from the source-file percentages. Credentials, installed dependencies, caches, runtime/model files, archives and unrelated local files are excluded.

## Three-part allocation

| Part | Source files | Actual share | Requested share |
|---|---:|---:|---:|
| Murali_backend | 43 | 50.00% | 50% |
| Part2_frontend_operations | 22 | 25.58% | 25% |
| Part3_ai_quality | 21 | 24.42% | 25% |

86 / 4 = 21.5. Whole files give 43 / 22 / 21: exact 50%, with the closest whole-file quarters. No source file was split or padded.

Counts describe file allocation, not authorship or development effort. The other two parts are not included in the backend branch upload.

## Included source tree

```text
Murali_backend/
└── backend/
    ├── app/
    │   ├── api/
    │   │   └── v1/
    │   │       └── endpoints/
    │   │           ├── feedback.py
    │   │           ├── health.py
    │   │           ├── queries.py
    │   │           └── runs.py
    │   ├── core/
    │   │   ├── config.py
    │   │   ├── database.py
    │   │   ├── evidence.py
    │   │   ├── neon_dns.py
    │   │   ├── outbox.py
    │   │   ├── outbox_reconcile.py
    │   │   ├── quarantine.py
    │   │   ├── security.py
    │   │   ├── state_machine.py
    │   │   └── telemetry.py
    │   ├── main.py
    │   ├── models/
    │   │   ├── base.py
    │   │   └── compliance.py
    │   └── schemas/
    │       └── compliance.py
    ├── ingestion/
    │   ├── cli.py
    │   ├── models.py
    │   └── parser.py
    ├── llm/
    │   └── adapter.py
    ├── migrations/
    │   ├── env.py
    │   └── versions/
    │       ├── 0001_initial.py
    │       └── 0002_legacy_safety.py
    ├── retrieval/
    │   ├── bm25_index.py
    │   ├── hybrid_search.py
    │   ├── temporal.py
    │   └── vector_store.py
    └── worker/
        ├── agents/
        │   ├── accounting.py
        │   ├── graph.py
        │   └── schemas.py
        ├── celery_app.py
        ├── core/
        │   └── circuit_breaker.py
        ├── guardrails/
        │   ├── input_guard.py
        │   └── output_guard.py
        ├── heartbeat.py
        ├── tasks.py
        └── tools/
            ├── corpus_search.py
            ├── provision_lookup.py
            ├── related_provision_lookup.py
            ├── request_fact_lookup.py
            └── temporal_status_lookup.py
```

[Full allocation tree](docs/code-split.tree.txt) · [File hashes and allocation manifest](docs/code-split.json)
