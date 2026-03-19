"""
NexusOps Knowledge Ingestion Pipeline
========================================
Continuously ingests runbooks, incident post-mortems, and documentation
into the Qdrant vector database for RAG retrieval.

Pipeline stages:
  1. LOAD    — Read documents from various sources (files, URLs, APIs)
  2. CHUNK   — Split documents into semantically meaningful chunks
  3. EMBED   — Generate vector embeddings for each chunk
  4. STORE   — Upsert vectors into Qdrant with metadata

Supports:
  - Markdown files (.md)
  - Plain text files (.txt)
  - JSON structured documents
  - Confluence-style wiki pages (extensible)
"""

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("nexusops.ingestion")


class DocumentChunk(BaseModel):
    """A single chunk of a document, ready for embedding and storage."""
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    source_file: str
    source_type: str = "runbook"
    chunk_index: int = 0
    total_chunks: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""


class IngestionConfig(BaseModel):
    """Configuration for the ingestion pipeline."""
    source_directory: str = "./knowledge_base"
    chunk_size: int = 800          # characters per chunk
    chunk_overlap: int = 100       # overlap between chunks
    supported_extensions: List[str] = [".md", ".txt", ".json"]
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "nexusops-knowledge"
    embedding_dimension: int = 1024


class KnowledgeIngestionPipeline:
    """
    End-to-end pipeline for ingesting documents into the vector database.
    """

    def __init__(self, config: IngestionConfig):
        self.config = config
        self._ingested_hashes: set = set()

    # ─── Stage 1: Load ───────────────────────────────────────────────────

    def discover_documents(self) -> List[Path]:
        """Scan the source directory for supported document types."""
        source_dir = Path(self.config.source_directory)
        if not source_dir.exists():
            source_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created knowledge base directory: {source_dir}")
            return []

        documents = []
        for ext in self.config.supported_extensions:
            documents.extend(source_dir.rglob(f"*{ext}"))

        logger.info(f"Discovered {len(documents)} documents in {source_dir}")
        return sorted(documents)

    # ─── Stage 2: Chunk ──────────────────────────────────────────────────

    def chunk_document(self, file_path: Path) -> List[DocumentChunk]:
        """Split a document into overlapping chunks."""
        content = file_path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Skip if already ingested (deduplication)
        if content_hash in self._ingested_hashes:
            logger.debug(f"Skipping already-ingested document: {file_path.name}")
            return []
        self._ingested_hashes.add(content_hash)

        # Split by paragraphs first, then by chunk_size
        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk = ""
        chunk_index = 0

        for para in paragraphs:
            if len(current_chunk) + len(para) > self.config.chunk_size:
                if current_chunk.strip():
                    chunks.append(DocumentChunk(
                        content=current_chunk.strip(),
                        source_file=str(file_path),
                        source_type=self._infer_source_type(file_path),
                        chunk_index=chunk_index,
                        content_hash=content_hash,
                        metadata={
                            "filename": file_path.name,
                            "directory": str(file_path.parent),
                            "extension": file_path.suffix,
                        },
                    ))
                    chunk_index += 1
                    # Keep overlap
                    overlap_text = current_chunk[-self.config.chunk_overlap:] if len(current_chunk) > self.config.chunk_overlap else ""
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk += "\n\n" + para if current_chunk else para

        # Final chunk
        if current_chunk.strip():
            chunks.append(DocumentChunk(
                content=current_chunk.strip(),
                source_file=str(file_path),
                source_type=self._infer_source_type(file_path),
                chunk_index=chunk_index,
                content_hash=content_hash,
                metadata={
                    "filename": file_path.name,
                    "directory": str(file_path.parent),
                    "extension": file_path.suffix,
                },
            ))

        # Set total_chunks on all
        for c in chunks:
            c.total_chunks = len(chunks)

        logger.info(f"Chunked {file_path.name} → {len(chunks)} chunks")
        return chunks

    def _infer_source_type(self, path: Path) -> str:
        """Infer document type from path or content."""
        name = path.name.lower()
        if "runbook" in name or "rb-" in name:
            return "runbook"
        elif "postmortem" in name or "incident" in name:
            return "incident_postmortem"
        elif "readme" in name:
            return "documentation"
        elif "playbook" in name:
            return "playbook"
        return "documentation"

    # ─── Stage 3 & 4: Embed + Store ──────────────────────────────────────

    def ingest_all(self) -> Dict[str, Any]:
        """Run the full ingestion pipeline."""
        documents = self.discover_documents()
        total_chunks = 0
        total_documents = 0

        for doc_path in documents:
            try:
                chunks = self.chunk_document(doc_path)
                if chunks:
                    # In production: embed chunks and upsert to Qdrant
                    # For now, we log the chunks
                    total_chunks += len(chunks)
                    total_documents += 1
                    logger.info(f"Ingested: {doc_path.name} ({len(chunks)} chunks)")
            except Exception as e:
                logger.error(f"Failed to ingest {doc_path.name}: {e}")

        result = {
            "documents_processed": total_documents,
            "total_chunks_created": total_chunks,
            "documents_skipped": len(documents) - total_documents,
            "collection": self.config.collection_name,
        }
        logger.info(f"Ingestion complete: {result}")
        return result
