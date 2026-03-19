from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import requests

class RetrieverConfig(BaseModel):
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "nexusops-knowledge"
    embedding_endpoint: str = "http://localhost:5001/embed" # Mock
    reranker_endpoint: str = "http://localhost:5002/rerank" # Mock
    top_k_retrieval: int = 50
    top_k_output: int = 5

class RetrievedDocument(BaseModel):
    content: str
    metadata: Dict[str, Any]
    score: float

class DocumentRetriever:
    def __init__(self, config: RetrieverConfig):
        self.config = config
        self.client = QdrantClient(url=config.qdrant_url)

    def _embed_query(self, query: str) -> List[float]:
        # Mock embedding call
        resp = requests.post(self.config.embedding_endpoint, json={"text": query})
        if resp.status_code == 200:
            return resp.json().get("embedding", [])
        return [0.0] * 1024 # fallback

    def retrieve(self, query: str, filters: Optional[Dict[str, str]] = None) -> List[RetrievedDocument]:
        vector = self._embed_query(query)
        
        qdrant_filter = None
        if filters:
            conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
            qdrant_filter = Filter(must=conditions)
            
        search_result = self.client.search(
            collection_name=self.config.collection_name,
            query_vector=vector,
            query_filter=qdrant_filter,
            limit=self.config.top_k_retrieval
        )
        
        # Mock Reranker 
        docs = []
        for scored_point in search_result:
            docs.append(RetrievedDocument(
                content=scored_point.payload.get("content", ""),
                metadata=scored_point.payload,
                score=scored_point.score
            ))
            
        # Return top N (simulating post-reranking)
        return sorted(docs, key=lambda x: x.score, reverse=True)[:self.config.top_k_output]
