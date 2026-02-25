"""ChromaDB vector store for semantic search."""

from __future__ import annotations

import logging
from pathlib import Path

import chromadb

from .config import COLLECTION_NAME
from .models import ConversationChunk

logger = logging.getLogger(__name__)


class ConversationVectorStore:
    """ChromaDB-backed vector store for conversation chunks."""

    def __init__(self, persist_path: Path):
        persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: list[ConversationChunk], batch_size: int = 100):
        """Add conversation chunks to the vector store in batches."""
        if not chunks:
            return

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            ids = [f"{c.conversation_id}__chunk_{c.chunk_index}" for c in batch]
            documents = [c.text for c in batch]
            metadatas = [
                {
                    "conversation_id": c.conversation_id,
                    "conversation_title": c.conversation_title,
                    "chunk_index": c.chunk_index,
                    "first_timestamp": c.first_timestamp or 0.0,
                    "last_timestamp": c.last_timestamp or 0.0,
                }
                for c in batch
            ]

            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def search(self, query: str, n_results: int = 10) -> list[dict]:
        """Semantic search across all conversation chunks.

        Returns a list of dicts with: conversation_id, title, score, snippet, timestamp.
        """
        count = self.collection.count()
        if count == 0:
            return []

        # Don't request more results than we have documents
        actual_n = min(n_results * 3, count)  # Over-fetch to deduplicate by conversation

        results = self.collection.query(
            query_texts=[query],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        # Deduplicate by conversation_id, keeping the best match per conversation
        seen: dict[str, dict] = {}

        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            document = results["documents"][0][i]
            conv_id = meta["conversation_id"]

            # Cosine distance → similarity score (0 = identical, 2 = opposite)
            score = 1.0 - distance

            if conv_id not in seen or score > seen[conv_id]["score"]:
                seen[conv_id] = {
                    "conversation_id": conv_id,
                    "title": meta["conversation_title"],
                    "score": round(score, 4),
                    "snippet": document[:200] + "..." if len(document) > 200 else document,
                    "timestamp": meta.get("first_timestamp") or None,
                }

        # Sort by score descending, limit to requested amount
        results_list = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
        return results_list[:n_results]

    def delete_conversation(self, conversation_id: str):
        """Remove all chunks for a conversation."""
        self.collection.delete(where={"conversation_id": conversation_id})

    def count(self) -> int:
        return self.collection.count()
