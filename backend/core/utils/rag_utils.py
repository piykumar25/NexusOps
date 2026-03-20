"""
NexusOps RAG (Retrieval-Augmented Generation) Utilities
========================================================
Production-grade document retrieval using Qdrant vector database.
Automatically creates collections, handles embedding, and provides
graceful degradation when services are unavailable.

Features:
  - Uses the unified EmbeddingService (Ollama/OpenAI/Fallback)
  - Auto-creates Qdrant collection if it doesn't exist
  - Graceful degradation: returns empty results if Qdrant or embeddings are down
  - Configurable collection name, top-k, and score threshold
"""

import logging
import os
import warnings
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexusops.rag")

# Suppress Qdrant client version mismatch warnings
warnings.filterwarnings("ignore", message=".*qdrant.*version.*")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "nexusops-knowledge")


class DocumentRetriever:
    """
    Retrieves relevant documents from Qdrant using semantic search.
    Gracefully degrades when Qdrant or the embedding service is unavailable.
    """

    def __init__(
        self,
        qdrant_url: str = QDRANT_URL,
        collection_name: str = COLLECTION_NAME,
        top_k: int = 5,
        score_threshold: float = 0.3,
    ):
        self.collection_name = collection_name
        self.top_k = top_k
        self.score_threshold = score_threshold
        self.client = None
        self._embedding_provider = None

        # Initialize Qdrant client
        try:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(
                url=qdrant_url,
                timeout=10,
                check_compatibility=False,
            )
            logger.info(f"Qdrant client connected: {qdrant_url}")
            self._ensure_collection_exists()
        except Exception as e:
            logger.warning(f"Qdrant client initialization failed: {e}. RAG retrieval will return empty results.")
            self.client = None

        # Initialize embedding provider
        try:
            from backend.core.utils.embedding_service import get_embedding_provider
            self._embedding_provider = get_embedding_provider()
            logger.info(f"Embedding provider ready: dim={self._embedding_provider.dimension}")
        except Exception as e:
            logger.warning(f"Embedding provider initialization failed: {e}. RAG retrieval will return empty results.")

    def _ensure_collection_exists(self):
        """Create the collection if it doesn't exist."""
        if self.client is None:
            return

        try:
            from qdrant_client.models import Distance, VectorParams
            from backend.core.utils.embedding_service import get_embedding_provider

            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                provider = get_embedding_provider()
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=provider.dimension,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name} (dim={provider.dimension})")
            else:
                logger.debug(f"Qdrant collection '{self.collection_name}' already exists")
        except Exception as e:
            logger.warning(f"Failed to ensure collection exists: {e}")

    def _embed_query(self, query: str) -> List[float]:
        """Generate embedding vector for a query. Returns zero vector on failure."""
        if self._embedding_provider is None:
            try:
                from backend.core.utils.embedding_service import get_embedding_provider
                self._embedding_provider = get_embedding_provider()
            except Exception:
                logger.warning("Embedding provider not available")
                return [0.0] * 768

        return self._embedding_provider.embed(query)

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve the most relevant documents for a query.
        Returns a list of dicts with 'content', 'score', and 'metadata' keys.
        Returns empty list if Qdrant or embedding service is unavailable.
        """
        if self.client is None:
            logger.debug("Qdrant client not available — returning empty results")
            return []

        try:
            query_vector = self._embed_query(query)

            # Check if it's a zero vector (no real embedding)
            if all(v == 0.0 for v in query_vector[:10]):
                logger.debug("Embedding is a zero vector — returning empty results")
                return []

            # Use query_points (modern Qdrant API)
            from qdrant_client.models import Filter

            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=self.top_k,
                score_threshold=self.score_threshold,
            )

            documents = []
            points = results.points if hasattr(results, 'points') else results
            for point in points:
                payload = point.payload or {}
                documents.append({
                    "content": payload.get("content", payload.get("text", "")),
                    "score": point.score if hasattr(point, 'score') else 0.0,
                    "metadata": {
                        k: v for k, v in payload.items()
                        if k not in ("content", "text")
                    },
                })

            logger.info(f"RAG retrieved {len(documents)} documents for query: '{query[:60]}...'")
            return documents

        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}. Returning empty results.")
            return []

    def ingest(self, documents: List[Dict[str, Any]], batch_size: int = 50) -> int:
        """
        Ingest documents into Qdrant.

        Each document should be a dict with at least a 'content' key.
        Optional keys: 'title', 'source', 'category', etc. (stored as payload).

        Returns the number of documents successfully ingested.
        """
        if self.client is None or self._embedding_provider is None:
            logger.warning("Cannot ingest — Qdrant client or embedding provider not available")
            return 0

        try:
            from qdrant_client.models import PointStruct
            import uuid

            total_ingested = 0

            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                texts = [doc.get("content", doc.get("text", "")) for doc in batch]
                embeddings = self._embedding_provider.embed_batch(texts)

                points = []
                for doc, embedding in zip(batch, embeddings):
                    point_id = str(uuid.uuid4())
                    payload = {**doc}  # Copy all fields as payload
                    points.append(PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=payload,
                    ))

                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                total_ingested += len(points)

            logger.info(f"Ingested {total_ingested} documents into '{self.collection_name}'")
            return total_ingested

        except Exception as e:
            logger.error(f"Document ingestion failed: {e}")
            return 0
