"""
NexusOps Embedding Service
============================
Unified embedding interface supporting multiple providers.
Automatically selects the best available provider based on configuration.

Supported Providers:
  1. Ollama (default, free, local) — nomic-embed-text or any Ollama embedding model
  2. OpenAI — text-embedding-3-small / text-embedding-ada-002
  3. Fallback — Zero vectors (when no embedding service is available)

Configuration via environment variables:
  EMBEDDING_PROVIDER: "ollama" | "openai" | "fallback" (default: "ollama")
  EMBEDDING_MODEL: model name (default: "nomic-embed-text" for Ollama)
  EMBEDDING_DIM: vector dimension (default: 768 for nomic-embed-text)
  OLLAMA_BASE_URL: Ollama server URL (default: "http://localhost:11434")
  OPENAI_API_KEY: required if provider is "openai"
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx

logger = logging.getLogger("nexusops.embedding")

# ─── Configuration ───────────────────────────────────────────────────────────

EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "ollama")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
OLLAMA_HOST = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").replace("/v1", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


# ─── Abstract Provider ──────────────────────────────────────────────────────

class EmbeddingProvider(ABC):
    """Abstract base class for all embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for the given text."""
        ...

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a batch of texts."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        ...


# ─── Ollama Provider ────────────────────────────────────────────────────────

class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Generate embeddings using Ollama's /api/embed endpoint.
    Default model: nomic-embed-text (768 dimensions, fast, free).
    """

    def __init__(self, base_url: str = OLLAMA_HOST, model: str = EMBEDDING_MODEL, dim: int = EMBEDDING_DIM):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._dim = dim
        self._client = httpx.Client(timeout=30.0)
        logger.info(f"OllamaEmbeddingProvider initialized: model={model}, dim={dim}, url={self.base_url}")

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text using Ollama."""
        try:
            response = self._client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            data = response.json()

            # Ollama returns {"embeddings": [[...]]} for /api/embed
            embeddings = data.get("embeddings", [])
            if embeddings and len(embeddings) > 0:
                return embeddings[0]

            logger.warning(f"Ollama returned empty embeddings for text: '{text[:50]}...'")
            return [0.0] * self._dim

        except httpx.ConnectError:
            logger.warning("Ollama embedding service not reachable. Returning zero vector.")
            return [0.0] * self._dim
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return [0.0] * self._dim

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        try:
            response = self._client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()

            embeddings = data.get("embeddings", [])
            if embeddings and len(embeddings) == len(texts):
                return embeddings

            # Pad with zero vectors if needed
            result = list(embeddings) if embeddings else []
            while len(result) < len(texts):
                result.append([0.0] * self._dim)
            return result

        except Exception as e:
            logger.error(f"Ollama batch embedding failed: {e}")
            return [[0.0] * self._dim for _ in texts]


# ─── OpenAI Provider ────────────────────────────────────────────────────────

class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Generate embeddings using OpenAI's embedding API.
    Default model: text-embedding-3-small (1536 dimensions).
    """

    def __init__(self, api_key: str = OPENAI_API_KEY, model: str = "text-embedding-3-small", dim: int = 1536):
        self.api_key = api_key
        self.model = model
        self._dim = dim
        self._client = httpx.Client(timeout=30.0)
        logger.info(f"OpenAIEmbeddingProvider initialized: model={model}, dim={dim}")

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text using OpenAI."""
        try:
            response = self._client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

        except Exception as e:
            logger.error(f"OpenAI embedding failed: {e}")
            return [0.0] * self._dim

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts using OpenAI."""
        try:
            response = self._client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]

        except Exception as e:
            logger.error(f"OpenAI batch embedding failed: {e}")
            return [[0.0] * self._dim for _ in texts]


# ─── Fallback Provider ──────────────────────────────────────────────────────

class FallbackEmbeddingProvider(EmbeddingProvider):
    """Zero-vector provider for when no embedding service is available."""

    def __init__(self, dim: int = EMBEDDING_DIM):
        self._dim = dim
        logger.warning(f"FallbackEmbeddingProvider active — all embeddings will be zero vectors (dim={dim})")

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return [0.0] * self._dim

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [[0.0] * self._dim for _ in texts]


# ─── Factory ────────────────────────────────────────────────────────────────

_provider_instance: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """
    Get or create the singleton embedding provider based on configuration.
    Thread-safe (creates on first call, reuses afterwards).
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    provider_name = EMBEDDING_PROVIDER.lower()

    if provider_name == "ollama":
        _provider_instance = OllamaEmbeddingProvider()
    elif provider_name == "openai":
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set — falling back to zero-vector embeddings")
            _provider_instance = FallbackEmbeddingProvider()
        else:
            _provider_instance = OpenAIEmbeddingProvider()
    else:
        _provider_instance = FallbackEmbeddingProvider()

    return _provider_instance
