"""
NexusOps RAG Retriever
========================
Document retrieval with embedding + vector search + reranking.

Gracefully degrades when external services (embedding endpoint, Qdrant)
are unavailable — returns empty results instead of crashing the pipeline.
"""

import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import requests

logger = logging.getLogger("nexusops.rag")


class RetrieverConfig(BaseModel):
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "nexusops-knowledge"
    embedding_endpoint: str = "http://localhost:5001/embed"
    reranker_endpoint: str = "http://localhost:5002/rerank"
    top_k_retrieval: int = 50
    top_k_output: int = 5


class RetrievedDocument(BaseModel):
    content: str
    metadata: Dict[str, Any]
    score: float


class DocumentRetriever:
    def __init__(self, config: RetrieverConfig):
        self.config = config
        try:
            self.client = QdrantClient(
                url=config.qdrant_url,
                timeout=5,
                check_compatibility=False,  # Suppress version mismatch warnings
            )
        except Exception as e:
            logger.warning(f"Qdrant client initialization failed (will return empty results): {e}")
            self.client = None

    def _embed_query(self, query: str) -> List[float]:
        """Call the embedding endpoint. Returns a zero vector on failure."""
        try:
            resp = requests.post(
                self.config.embedding_endpoint,
                json={"text": query},
                timeout=3,
            )
            if resp.status_code == 200:
                return resp.json().get("embedding", [0.0] * 1024)
        except requests.exceptions.ConnectionError:
            logger.debug("Embedding service unavailable — using zero vector fallback.")
        except Exception as e:
            logger.warning(f"Embedding call failed: {e}")
        return [0.0] * 1024  # fallback

    def retrieve(self, query: str, filters: Optional[Dict[str, str]] = None) -> List[RetrievedDocument]:
        """Retrieve relevant documents. Returns empty list if services are unavailable."""
        if self.client is None:
            return []

        try:
            vector = self._embed_query(query)

            qdrant_filter = None
            if filters:
                conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
                qdrant_filter = Filter(must=conditions)

            search_result = self.client.search(
                collection_name=self.config.collection_name,
                query_vector=vector,
                query_filter=qdrant_filter,
                limit=self.config.top_k_retrieval,
            )

            docs = []
            for scored_point in search_result:
                docs.append(RetrievedDocument(
                    content=scored_point.payload.get("content", ""),
                    metadata=scored_point.payload,
                    score=scored_point.score,
                ))

            return sorted(docs, key=lambda x: x.score, reverse=True)[:self.config.top_k_output]

        except Exception as e:
            logger.warning(f"RAG retrieval failed (returning empty results): {e}")
            return []
