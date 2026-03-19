<div align="center">

# ⚡ NexusOps

### AI-Powered DevOps Operations Center

*Intelligent infrastructure operations powered by multi-agent AI orchestration.*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Kafka](https://img.shields.io/badge/Apache_Kafka-7.5-231F20?logo=apachekafka&logoColor=white)](https://kafka.apache.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

---

## 🏗️ Architecture

NexusOps follows an **Event-Driven Microservices Architecture (EDA)** with a multi-agent AI orchestration layer.

```
┌─────────────────────────────────────────────────────────┐
│                  Next.js Frontend (:3000)                │
│        Dark Mode • Glassmorphism • Real-time Chat        │
├─────────────────────────────────────────────────────────┤
│                FastAPI Backend (:8082)                    │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │  REST API     │  │  WebSocket    │  │  Webhook     │  │
│  │  /api/chat    │  │  /ws/chat     │  │  Ingester    │  │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────┘  │
│         │                  │                  │          │
│  ┌──────┴──────────────────┴──────────────────┘          │
│  │           MasterCoordinator                           │
│  │  ┌────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │  │ DocsAgent  │ │ MetricsAgent │ │  K8sAgent    │    │
│  │  │ (RAG)      │ │ (Prometheus) │ │ (kubectl)    │    │
│  │  └────────────┘ └──────────────┘ └──────────────┘    │
│  └───────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                  Event Bus (Kafka)                        │
│  Topics: incident-alerts │ ai-data-stream │ triage-results│
├─────────────────────────────────────────────────────────┤
│  Qdrant (Vectors)  │  PostgreSQL (State)  │  Redis (Cache)│
└─────────────────────────────────────────────────────────┘
```

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Agent Orchestration** | Coordinator-Delegate pattern with specialized AI agents |
| **RAG Pipeline** | Dense retrieval + reranking over runbooks and incident history |
| **Real-time Streaming** | Token-by-token WebSocket streaming to the UI |
| **Event-Driven Triage** | 5-stage automated incident investigation pipeline |
| **Webhook Ingestion** | Adapters for Prometheus Alertmanager, PagerDuty, and custom sources |
| **Audit Logging** | Every LLM call, tool execution, and agent decision is logged |
| **Knowledge Ingestion** | Continuous pipeline for indexing runbooks into Qdrant |
| **Dead Letter Queue** | Poison messages are captured and logged, never dropped |

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Docker & Docker Compose (for infrastructure services)

### 1. Clone and Install

```bash
git clone https://github.com/piykumar25/NexusOps.git
cd NexusOps

# Backend
python -m venv .venv
.venv\Scripts\Activate.ps1     # Windows
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 2. Start Infrastructure (Optional — requires Docker)

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, Qdrant, and Kafka locally.

### 3. Run the Application

```bash
# Terminal 1: Backend API
uvicorn backend.api.main:app --host 0.0.0.0 --port 8082 --reload

# Terminal 2: Frontend
cd frontend && npm run dev
```

Open **http://localhost:3000** in your browser.

## 📂 Project Structure

```
NexusOps/
├── backend/
│   ├── api/
│   │   ├── main.py                    # FastAPI application
│   │   ├── routers/
│   │   │   └── websocket_router.py    # WebSocket streaming
│   │   └── webhooks/
│   │       └── ingester.py            # Webhook ingestion (PD/Prometheus)
│   └── core/
│       ├── agents/
│       │   ├── agent_base.py          # AgentBase contract
│       │   ├── pydantic_ai_agent.py   # PydanticAI wrapper
│       │   ├── coordinator.py         # MasterCoordinator
│       │   ├── specialists.py         # DocsAgent, K8sAgent
│       │   └── metrics_agent.py       # MetricsAgent (Prometheus)
│       ├── config/
│       │   └── base.py                # ConfigBase, LLMConfig
│       ├── db/
│       │   ├── database.py            # SQLAlchemy engine
│       │   └── models.py              # ORM models
│       ├── events/
│       │   ├── schemas.py             # Event schema registry
│       │   └── kafka_infra.py         # Kafka producer/consumer/DLQ
│       ├── memory/
│       │   ├── message_base.py        # UniversalMessage
│       │   └── conversation_service.py # Session persistence
│       ├── utils/
│       │   ├── rag_utils.py           # DocumentRetriever (Qdrant)
│       │   ├── audit_logger.py        # Enterprise audit logging
│       │   └── knowledge_ingestion.py # RAG document pipeline
│       └── workflows/
│           └── triage_pipeline.py     # 5-stage automated triage
├── frontend/                          # Next.js 16 + Tailwind CSS
│   └── src/
│       ├── app/
│       │   ├── globals.css            # Design system
│       │   ├── layout.tsx             # Root layout
│       │   └── page.tsx               # Chat interface
│       └── hooks/
│           └── useNexusWebSocket.ts   # WebSocket hook
├── knowledge_base/                    # Runbooks & incidents for RAG
├── docker-compose.yml                 # Local infrastructure
├── requirements.txt                   # Python dependencies
└── pyproject.toml                     # Project metadata
```

## 🧠 Agent Architecture

NexusOps uses a **Coordinator-Delegate** multi-agent pattern:

```
User Query → MasterCoordinator
                 ├── ask_docs_agent()    → DocsAgent (RAG over runbooks)
                 ├── ask_k8s_agent()     → K8sAgent (cluster inspection)
                 └── ask_metrics_agent() → MetricsAgent (Prometheus queries)
```

Each agent is built on `PydanticAI` with:
- Type-safe structured outputs via Pydantic models
- Tool registration with enable/disable at runtime
- Conversation memory via `UniversalMessage` format

## 🔄 Event-Driven Pipeline

```
Alert (PagerDuty/Prometheus)
  → POST /api/v1/webhooks/ingest/{source}
    → IncidentAlertEvent published to Kafka
      → TriagePipeline consumes event
        → Stage 1: Preprocessing
        → Stage 2: RAG Enrichment (DocsAgent)
        → Stage 3: Metrics Analysis (MetricsAgent)
        → Stage 4: K8s Inspection (K8sAgent)
        → Stage 5: Synthesis (Root Cause Hypothesis)
      → TriageResultEvent published
        → UI receives real-time updates via WebSocket
```

## 📜 License

MIT License — See [LICENSE](LICENSE) for details.

---

<div align="center">
  <strong>Built with ❤️ by <a href="https://github.com/piykumar25">piykumar25</a></strong>
</div>
