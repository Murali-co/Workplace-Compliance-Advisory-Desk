"""BM25 Okapi index for lexical keyword search over canonical provisions.

Provides exact token and phrase matching without requiring an external search cluster.
"""

import math
import re
from typing import Dict, List, Tuple

# Function words alone must never make an unrelated question a legal match.
STOP_WORDS = frozenset(
    "a an and are as at be been being by can could did do does for from had has have how i if in into is it its may me must my of on or our shall should so than that the their them then there these they this those to under up us was we were what when where whether which who why will with would you your".split()
)


def meaningful_terms(text):
    return {token for token in re.findall(r"\b\w+\b", text.lower()) if token not in STOP_WORDS}


class BM25Index:
    """In-memory BM25 Okapi keyword index."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avg_doc_len = 0.0
        self.doc_lengths: Dict[str, int] = {}
        self.doc_tokens: Dict[str, List[str]] = {}
        self.doc_metadata: Dict[str, dict] = {}
        self.term_doc_freq: Dict[str, int] = {}

    def _tokenize(self, text: str) -> List[str]:
        """Simple lowercase word tokenizer."""
        return [token for token in re.findall(r"\b\w+\b", text.lower()) if token not in STOP_WORDS]

    def build_index(self, documents: List[dict]) -> None:
        """Builds index from list of dicts with keys: provision_id, text, metadata."""
        self.corpus_size = len(documents)
        total_len = 0
        self.term_doc_freq.clear()
        self.doc_lengths.clear()
        self.doc_tokens.clear()
        self.doc_metadata.clear()

        for doc in documents:
            doc_id = doc["provision_id"]
            text = doc.get("text", "")
            tokens = self._tokenize(text)
            self.doc_tokens[doc_id] = tokens
            self.doc_lengths[doc_id] = len(tokens)
            self.doc_metadata[doc_id] = doc.get("metadata", {})
            total_len += len(tokens)

            # Record document frequency for terms
            unique_terms = set(tokens)
            for term in unique_terms:
                self.term_doc_freq[term] = self.term_doc_freq.get(term, 0) + 1

        self.avg_doc_len = (total_len / self.corpus_size) if self.corpus_size > 0 else 0.0

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float, dict]]:
        """Searches index and returns list of (doc_id, score, metadata) ranked by BM25 score."""
        query_tokens = self._tokenize(query)
        if not query_tokens or self.corpus_size == 0:
            return []

        scores: Dict[str, float] = {}

        for term in query_tokens:
            if term not in self.term_doc_freq:
                continue

            df = self.term_doc_freq[term]
            # Standard Lucene/BM25 IDF formula
            idf = math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1.0)

            for doc_id, tokens in self.doc_tokens.items():
                tf = tokens.count(term)
                if tf == 0:
                    continue

                doc_len = self.doc_lengths[doc_id]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                term_score = idf * (numerator / denominator)

                scores[doc_id] = scores.get(doc_id, 0.0) + term_score

        # Sort descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(doc_id, score, self.doc_metadata.get(doc_id, {})) for doc_id, score in ranked]
