"""Chroma Vector Store manager with local Sentence-Transformers embeddings.

Adheres to Requirement L1 and ADR-03:
- Uses local all-MiniLM-L6-v2 embeddings (zero external cost, privacy preserving).
- Re-embedding checks content hashes and updates without rebuilding unchanged vectors.
- Snapshot hash generated from corpus content fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger("retrieval.vector_store")


class VectorStoreManager:
    """Manages dense vector indexing and querying in Chroma."""

    def __init__(
        self,
        model_name: str = None,
        chroma_host: str = None,
        chroma_port: int = None,
        device: str = None,
    ):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.chroma_host = chroma_host or settings.CHROMA_HOST
        self.chroma_port = chroma_port or settings.CHROMA_PORT
        self.device = device or settings.EMBEDDING_DEVICE

        self._embedder: Optional[SentenceTransformer] = None
        self._client = None
        self._collection = None
        self.collection_name = settings.CHROMA_COLLECTION

    @property
    def embedder(self) -> SentenceTransformer:
        """Lazy-loads local sentence-transformers model."""
        if self._embedder is None:
            logger.info(
                "Loading local embedding model '%s' on %s...",
                self.model_name,
                self.device,
            )
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(
                self.model_name, device=self.device, cache_folder=settings.EMBEDDING_CACHE_DIR
            )
        return self._embedder

    @property
    def client(self):
        """Initializes ChromaDB client (HTTP or local persistent fallback)."""
        if self._client is None:
            if settings.CHROMA_LOCAL_PATH:
                self._client = chromadb.PersistentClient(
                    path=settings.CHROMA_LOCAL_PATH,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            else:
                self._client = chromadb.HttpClient(
                    host=self.chroma_host,
                    port=self.chroma_port,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._client.heartbeat()

        return self._client

    @property
    def collection(self):
        """Retrieves or creates the provisions collection."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "description": "Statutory provisions for Indian labour compliance",
                    "hnsw:space": "cosine",
                },
            )
        return self._collection

    def compute_embedding(self, text: str) -> List[float]:
        """Generates 384-dimensional dense vector for input text."""
        embedding = self.embedder.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def upsert_provisions(self, provisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Idempotently indexes provisions by checking content hashes.

        Avoids re-embedding unchanged documents.
        """
        if not provisions:
            return {"indexed": 0, "skipped": 0, "snapshot_hash": ""}

        # Fetch existing metadata from collection
        existing = self.collection.get(include=["metadatas"])
        existing_hashes = {}
        if existing and existing["ids"]:
            for prov_id, meta in zip(existing["ids"], existing["metadatas"]):
                if meta and "content_hash" in meta:
                    existing_hashes[prov_id] = meta["content_hash"]

        ids_to_embed = []
        documents_to_embed = []
        metadatas_to_embed = []
        skipped_count = 0

        for prov in provisions:
            prov_id = prov["provision_id"]
            prov_text = prov["provision_text"]
            content_hash = hashlib.sha256(
                json.dumps(
                    {
                        "model": self.model_name,
                        "provision": {
                            k: v for k, v in prov.items() if k not in {"created_at", "updated_at"}
                        },
                    },
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest()

            # Check if vector already exists with identical content
            if prov_id in existing_hashes and existing_hashes[prov_id] == content_hash:
                skipped_count += 1
                continue

            # Contextually enriched representation for vector indexing
            embed_text = (
                f"{prov['act']} | Section {prov['section']} {prov.get('clause') or ''} | "
                f"{prov.get('provision_type') or ''} | {prov_text}"
            )

            metadata = {
                "provision_id": prov_id,
                "act": prov["act"],
                "section": prov["section"],
                "clause": prov.get("clause") or "",
                "provision_type": prov.get("provision_type") or "Main Rule",
                "parent_provision": prov.get("parent_provision") or "",
                "legal_status": prov.get("legal_status") or "In Force",
                "effective_from": str(prov.get("effective_from") or ""),
                "effective_until": str(prov.get("effective_until") or ""),
                "content_hash": content_hash,
            }

            ids_to_embed.append(prov_id)
            documents_to_embed.append(embed_text)
            metadatas_to_embed.append(metadata)

        indexed_count = 0
        if ids_to_embed:
            logger.info("Computing embeddings for %d new/updated provisions...", len(ids_to_embed))
            embeddings = self.embedder.encode(
                documents_to_embed, normalize_embeddings=True
            ).tolist()

            self.collection.upsert(
                ids=ids_to_embed,
                embeddings=embeddings,
                documents=documents_to_embed,
                metadatas=metadatas_to_embed,
            )
            indexed_count = len(ids_to_embed)

        # Compute corpus snapshot fingerprint
        snapshot = self.collection.get(include=["metadatas"])
        all_ids = sorted(snapshot["ids"])
        hashes = sorted(
            (i, m.get("content_hash", "")) for i, m in zip(snapshot["ids"], snapshot["metadatas"])
        )
        snapshot_hash = hashlib.sha256(json.dumps([self.model_name, hashes]).encode()).hexdigest()

        logger.info(
            "Vector indexing complete: %d indexed, %d skipped. Snapshot: %s",
            indexed_count,
            skipped_count,
            snapshot_hash[:12],
        )
        return {
            "indexed": indexed_count,
            "skipped": skipped_count,
            "total": len(all_ids),
            "snapshot_hash": snapshot_hash,
        }

    def query_similar(
        self,
        query: str,
        top_k: int = 5,
        where_filter: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """Queries Chroma vector store with dense semantic similarity."""
        count = self.collection.count()
        if count == 0 or top_k < 1:
            return []
        query_embedding = self.compute_embedding(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, count),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if results and results["ids"] and results["ids"][0]:
            for i, prov_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i]
                doc = results["documents"][0][i]
                output.append(
                    {
                        "provision_id": prov_id,
                        "score": 1.0 - dist,  # Cosine similarity approximation
                        "document": doc,
                        "metadata": meta,
                    }
                )
        return output
