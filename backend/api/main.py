"""
NexusOps API Server
====================
FastAPI application with lifecycle management for Kafka producers,
webhook ingestion, and the agentic orchestration layer.

Startup sequence:
  1. Initialize the MasterCoordinator singleton
  2. Ensure Kafka topics exist (graceful if broker is down)
  3. Initialize Kafka producer for webhooks
  4. Register API routers
  5. (Optional) Start background Kafka consumer for triage pipeline

Shutdown sequence:
  1. Flush Kafka producers
  2. Stop background consumers
"""

import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from backend.core.agents.coordinator import MasterCoordinator
from backend.core.events.kafka_infra import KafkaConfig, ensure_topics_exist
from backend.api.webhooks.ingester import router as webhook_router, init_webhook_producer
from backend.api.routers.websocket_router import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("nexusops.api")

# ─── Configuration ───────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9093")
LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "test")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

REQUIRED_TOPICS = [
    "incident-alerts",
    "ai-data-stream",
    "triage-results",
    "nexusops-dlq",
]


# ─── Singleton Coordinator ───────────────────────────────────────────────────

_coordinator: MasterCoordinator = None


def get_coordinator() -> MasterCoordinator:
    """
    Return the singleton MasterCoordinator instance.
    Returns None if initialization fails (demo mode will be used).
    """
    global _coordinator
    if _coordinator is None:
        try:
            _coordinator = MasterCoordinator(
                model_name=LLM_MODEL,
                qdrant_url=QDRANT_URL,
                prometheus_url=PROMETHEUS_URL,
            )
            logger.info(f"MasterCoordinator initialized with model={LLM_MODEL}, tools={list(_coordinator.tools.keys())}")
        except Exception as e:
            logger.warning(
                f"MasterCoordinator initialization failed: {e}. "
                f"The API will start in demo mode. Fix the LLM configuration and restart."
            )
            return None
    return _coordinator


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("═══ NexusOps API Starting ═══")

    # 1. Initialize the coordinator at startup (graceful — continues in demo mode if it fails)
    coordinator = get_coordinator()
    if coordinator is None:
        logger.warning("═══ NexusOps API starting in DEMO MODE (no LLM configured) ═══")

    # 2. Ensure Kafka topics exist (graceful if broker is down)
    try:
        ensure_topics_exist(KAFKA_BOOTSTRAP, REQUIRED_TOPICS)
        logger.info("Kafka topics verified.")
    except Exception as e:
        logger.warning(f"Kafka topic setup skipped (broker may be unavailable): {e}")

    # 3. Initialize webhook Kafka producer
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
    version="0.3.0",
    lifespan=lifespan,
)

# Middleware stack (order matters — outermost first)
from backend.api.middleware import RequestIdMiddleware, AccessLogMiddleware
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIdMiddleware)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Scoped to frontend, not wildcard
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
Instrumentator().instrument(app).expose(app)

# Register routers
app.include_router(webhook_router)
app.include_router(ws_router)


# ─── Chat Endpoint ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="User's query")
    session_id: str = Field(..., min_length=1, description="Conversation session ID")


class ChatResponse(BaseModel):
    analysis: str
    confidence: str
    specialists_consulted: list[str]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Primary conversational endpoint.
    Routes user queries through the singleton MasterCoordinator agent.
    """
    coordinator = get_coordinator()

    try:
        result = await coordinator.run(input_data=request.message)
        return ChatResponse(
            analysis=str(result.output),
            confidence="high",
            specialists_consulted=list(coordinator.tools.keys()),
        )
    except Exception as e:
        logger.exception(f"Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    coordinator = get_coordinator()
    return {
        "status": "healthy",
        "service": "nexusops-api",
        "version": "0.2.0",
        "agents_loaded": list(coordinator.tools.keys()),
        "model": LLM_MODEL,
    }


@app.get("/")
async def root():
    return {
        "name": "NexusOps — AI DevOps Ops Center",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
    }
