"""
NexusOps API Server
====================
FastAPI application with lifecycle management for Kafka producers,
webhook ingestion, and the agentic orchestration layer.

Startup sequence:
  1. Ensure Kafka topics exist
  2. Initialize Kafka producer for webhooks
  3. Register API routers
  4. (Optional) Start background Kafka consumer for triage pipeline

Shutdown sequence:
  1. Flush Kafka producers
  2. Stop background consumers
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.agents.coordinator import MasterCoordinator
from backend.core.memory.conversation_service import ConversationService
from backend.core.db.database import get_db
from backend.core.events.kafka_infra import KafkaConfig, NexusKafkaProducer, ensure_topics_exist
from backend.api.webhooks.ingester import router as webhook_router, init_webhook_producer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("nexusops.api")

# ─── Configuration ───────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9093")
LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "test")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

REQUIRED_TOPICS = [
    "incident-alerts",
    "ai-data-stream",
    "triage-results",
    "nexusops-dlq",
]


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("═══ NexusOps API Starting ═══")

    # 1. Ensure Kafka topics exist
    try:
        ensure_topics_exist(KAFKA_BOOTSTRAP, REQUIRED_TOPICS)
        logger.info("Kafka topics verified.")
    except Exception as e:
        logger.warning(f"Kafka topic setup skipped (broker may be unavailable): {e}")

    # 2. Initialize webhook Kafka producer
    try:
        kafka_config = KafkaConfig(bootstrap_servers=KAFKA_BOOTSTRAP)
        init_webhook_producer(kafka_config)
        logger.info("Webhook Kafka producer ready.")
    except Exception as e:
        logger.warning(f"Webhook producer initialization skipped: {e}")

    logger.info("═══ NexusOps API Ready ═══")
    yield

    # Shutdown
    logger.info("═══ NexusOps API Shutting Down ═══")


# ─── Application ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="NexusOps — AI DevOps Ops Center",
    description="Intelligent infrastructure operations powered by multi-agent AI orchestration.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(webhook_router)


# ─── Chat Endpoint ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    analysis: str
    confidence: str
    specialists_consulted: list


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Primary conversational endpoint.
    Routes user queries through the MasterCoordinator agent.
    """
    coordinator = MasterCoordinator(model_name=LLM_MODEL, qdrant_url=QDRANT_URL)

    try:
        result = await coordinator.run(input_data=request.message)
        return ChatResponse(
            analysis=str(result.output),
            confidence="high",
            specialists_consulted=list(coordinator.tools.keys()),
        )
    except Exception as e:
        logger.exception(f"Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "nexusops-api",
        "version": "0.1.0",
    }


@app.get("/")
async def root():
    return {
        "name": "NexusOps — AI DevOps Ops Center",
        "version": "0.1.0",
        "docs": "/docs",
    }
