# NexusOps — System Architecture

> AI-Powered DevOps Operations Center — Complete Technical Architecture

---

## High-Level System Overview

```mermaid
graph TB
    subgraph "Frontend — Next.js 16"
        UI["Operations Console<br/>(React + TypeScript)"]
        WS_HOOK["useNexusWebSocket<br/>(Auto-reconnect Hook)"]
    end

    subgraph "API Layer — FastAPI"
        API["FastAPI Server<br/>:8082"]
        WS_EP["WebSocket /ws/chat"]
        REST_EP["REST /api/chat"]
        WH_EP["POST /webhooks/*"]
    end

    subgraph "Agentic Orchestration Engine"
        MC["MasterCoordinator<br/>(Central Orchestrator)"]
        DA["DocsAgent<br/>(RAG + Runbooks)"]
        K8A["K8sAgent<br/>(Cluster Inspector)"]
        MA["MetricsAgent<br/>(Prometheus Analyst)"]
    end

    subgraph "Infrastructure Services"
        KAFKA["Apache Kafka<br/>:9093"]
        PG["PostgreSQL 15<br/>:5432"]
        QDRANT["Qdrant Vector DB<br/>:6333"]
        REDIS["Redis 7<br/>:6379"]
        OLLAMA["Ollama LLM<br/>:11434"]
    end

    UI <-->|WebSocket| WS_EP
    UI -->|HTTP| REST_EP
    WS_HOOK --> UI

    WS_EP --> MC
    REST_EP --> MC

    MC -->|"ask_docs_agent"| DA
    MC -->|"ask_k8s_agent"| K8A
    MC -->|"ask_metrics_agent"| MA

    DA -->|"Vector Search"| QDRANT
    MA -->|"PromQL"| PROM["Prometheus<br/>:9090"]
    MC -->|"LLM Inference"| OLLAMA

    WH_EP -->|"Publish Events"| KAFKA
    KAFKA -->|"Consume"| TRIAGE["Triage Pipeline"]
    MC -->|"Session History"| PG

    style MC fill:#6366f1,stroke:#4f46e5,color:#fff
    style DA fill:#10b981,stroke:#059669,color:#fff
    style K8A fill:#f59e0b,stroke:#d97706,color:#fff
    style MA fill:#ef4444,stroke:#dc2626,color:#fff
    style OLLAMA fill:#8b5cf6,stroke:#7c3aed,color:#fff
```

---

## Agent Architecture

### Agent Hierarchy

```mermaid
classDiagram
    class AgentBase {
        +AgentMetadata metadata
        +Dict tools
        +add_tool(tool, name, enabled)
        +enable_tool(name)
        +disable_tool(name)
        +run(input_data, message_history, context)*
    }

    class PydanticAIAgent {
        -Agent _pydantic_agent
        +add_tool() wraps with functools
        +run() version-safe result extraction
        -_extract_result_data(result)
        -_extract_usage(result)
        -_extract_new_messages(result)
    }

    class MasterCoordinator {
        +DocsAgent docs_agent
        +K8sAgent k8s_agent
        +MetricsAgent metrics_agent
        -_register_delegations()
        +ask_docs(query) → str
        +ask_k8s(query) → str
        +ask_metrics(query) → str
    }

    class DocsAgent {
        +DocumentRetriever retriever
        +search_runbooks(query) → str
    }

    class K8sAgent {
        +get_pods(namespace) → str
        +get_events(namespace) → str
    }

    class MetricsAgent {
        +query_prometheus(promql, service) → str
        +get_service_health_summary(service) → str
    }

    AgentBase <|-- PydanticAIAgent
    PydanticAIAgent <|-- MasterCoordinator
    PydanticAIAgent <|-- DocsAgent
    PydanticAIAgent <|-- K8sAgent
    PydanticAIAgent <|-- MetricsAgent
    MasterCoordinator o-- DocsAgent
    MasterCoordinator o-- K8sAgent
    MasterCoordinator o-- MetricsAgent
```

### Agent Data Models

| Agent | Output Model | Fields |
|-------|-------------|--------|
| **MasterCoordinator** | `NexusOpsOutput` | `analysis`, `confidence`, `specialists_consulted` |
| **DocsAgent** | `DocsAgentOutput` | `answer`, `sources` |
| **K8sAgent** | `K8sAgentOutput` | `finding`, `actions_taken` |
| **MetricsAgent** | `MetricsOutput` | `summary`, `metrics_data`, `anomalies_detected` |

---

## Request Flow — Chat Query

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant WebSocket
    participant Coordinator as MasterCoordinator
    participant Docs as DocsAgent
    participant K8s as K8sAgent
    participant Metrics as MetricsAgent
    participant LLM as Ollama/LLM

    User->>Frontend: "Why is payment-service crashing?"
    Frontend->>WebSocket: { type: "chat", message: "..." }
    WebSocket->>Coordinator: run(input_data=message)

    Note over Coordinator,LLM: LLM decides which tools to call

    Coordinator->>LLM: System prompt + user query + tool definitions
    LLM-->>Coordinator: Tool call: ask_k8s_agent(query="pod status")

    Coordinator->>K8s: run("pod status")
    K8s->>LLM: "Analyze cluster state"
    LLM-->>K8s: Tool call: get_pods(namespace="default")
    K8s-->>Coordinator: "CrashLoopBackOff, 7 restarts"

    Coordinator->>LLM: Tool result + "call more tools?"
    LLM-->>Coordinator: Tool call: ask_metrics_agent(query="error rates")

    Coordinator->>Metrics: run("error rates")
    Metrics->>LLM: "Query Prometheus"
    LLM-->>Metrics: Tool call: get_service_health_summary("payment")
    Metrics-->>Coordinator: "CPU 94%, Memory 98%, 5xx 34%"

    Coordinator->>LLM: All tool results → synthesize
    LLM-->>Coordinator: NexusOpsOutput(analysis="Root cause: memory leak...")

    Coordinator-->>WebSocket: AgentResult
    WebSocket-->>Frontend: Token-by-token streaming
    Frontend-->>User: Rendered markdown response
```

---

## Event-Driven Pipeline (Kafka)

```mermaid
flowchart LR
    subgraph "Ingestion"
        GH["GitHub Webhook"]
        PD["PagerDuty Alert"]
        DD["Datadog Alert"]
    end

    subgraph "Kafka Cluster"
        IA["incident-alerts"]
        ADS["ai-data-stream"]
        TR["triage-results"]
        DLQ["nexusops-dlq"]
    end

    subgraph "Processing"
        TP["Triage Pipeline<br/>(NexusKafkaConsumer)"]
        MC2["MasterCoordinator"]
    end

    GH -->|"POST /webhooks/github"| IA
    PD -->|"POST /webhooks/pagerduty"| IA
    DD -->|"POST /webhooks/datadog"| IA

    IA -->|"Consume"| TP
    TP -->|"AI Analysis"| MC2
    MC2 -->|"Results"| TR
    TP -->|"Poison Messages"| DLQ

    style IA fill:#ef4444,stroke:#dc2626,color:#fff
    style DLQ fill:#6b7280,stroke:#4b5563,color:#fff
```

### Kafka Topics

| Topic | Purpose | Partitions |
|-------|---------|-----------|
| `incident-alerts` | Incoming webhook events | 3 |
| `ai-data-stream` | Internal agent communication | 3 |
| `triage-results` | Completed analysis results | 3 |
| `nexusops-dlq` | Dead letter queue for failed messages | 3 |

---

## Data Layer

```mermaid
erDiagram
    CONVERSATION_SESSION {
        int id PK
        string session_id UK
        json history
        datetime created_at
        datetime updated_at
    }

    NEXUS_EVENT {
        string event_id PK
        string event_type
        json payload
        json metadata
        datetime timestamp
    }

    QDRANT_COLLECTION {
        string collection_name
        int vector_dimension "1024"
        string distance_metric "Cosine"
    }

    CONVERSATION_SESSION ||--o{ NEXUS_EVENT : "triggers"
```

### Storage Services

| Service | Role | Port | Data |
|---------|------|------|------|
| **PostgreSQL 15** | Relational DB | 5432 | Conversation sessions, audit logs |
| **Qdrant** | Vector DB | 6333 | Runbook embeddings, knowledge base |
| **Redis 7** | Cache / Pub-Sub | 6379 | Session cache, rate limiting |
| **Kafka** | Event Streaming | 9093 | Incident alerts, triage pipeline |

---

## WebSocket Protocol

### Client → Server

```json
{ "type": "chat", "session_id": "...", "message": "Why is payment-service down?" }
{ "type": "ping" }
```

### Server → Client (Streamed)

```json
{ "type": "connected",    "session_id": "uuid" }
{ "type": "status",       "content": "Analyzing your query...", "done": false }
{ "type": "tool_call",    "tool": "ask_k8s_agent", "status": "running" }
{ "type": "tool_result",  "tool": "ask_k8s_agent", "result": "complete" }
{ "type": "token",        "content": "Based on ", "done": false }
{ "type": "complete",     "content": "full response...", "done": true }
{ "type": "error",        "message": "..." }
```

---

## Directory Structure

```
NexusOps/
├── backend/
│   ├── api/
│   │   ├── main.py                    # FastAPI app, lifespan, singleton coordinator
│   │   ├── routers/
│   │   │   └── websocket_router.py    # WebSocket streaming, demo/real LLM modes
│   │   └── webhooks/
│   │       └── ingester.py            # GitHub/PagerDuty/Datadog webhook ingestion
│   └── core/
│       ├── agents/
│       │   ├── agent_base.py          # AgentBase, AgentResult, ToolConfig contracts
│       │   ├── pydantic_ai_agent.py   # PydanticAI wrapper (version-safe)
│       │   ├── coordinator.py         # MasterCoordinator orchestrator
│       │   ├── specialists.py         # DocsAgent, K8sAgent
│       │   └── metrics_agent.py       # MetricsAgent (Prometheus)
│       ├── config/
│       │   └── base.py                # ConfigBase, LLMConfig
│       ├── db/
│       │   ├── database.py            # SQLAlchemy engine + session factory
│       │   └── models.py              # ConversationSession model
│       ├── events/
│       │   ├── kafka_infra.py         # Producer, Consumer, topic management
│       │   └── schemas.py             # NexusEvent Pydantic schemas
│       ├── memory/
│       │   ├── message_base.py        # UniversalMessage, MessageHistoryBase
│       │   └── conversation_service.py# Session load/save bridge
│       ├── utils/
│       │   └── rag_utils.py           # DocumentRetriever (Qdrant + embeddings)
│       └── workflows/
│           └── triage_pipeline.py     # Kafka-driven incident triage
├── frontend/
│   └── src/
│       ├── app/                       # Next.js 16 App Router
│       └── hooks/
│           └── useNexusWebSocket.ts   # Auto-reconnect WebSocket hook
├── docs/                              # ← You are here
├── docker-compose.yml                 # Postgres, Redis, Qdrant, Kafka, Zookeeper
├── pyproject.toml                     # Python project config
└── requirements.txt                   # Python dependencies
```

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **LLM Runtime** | Ollama (llama3.1 / llama3.2) | Latest |
| **AI Framework** | pydantic-ai | 1.70.0 |
| **API Server** | FastAPI + Uvicorn | 0.104+ |
| **Frontend** | Next.js (Turbopack) | 16.2.0 |
| **Database** | PostgreSQL | 15-alpine |
| **Vector DB** | Qdrant | 1.12.0 |
| **Cache** | Redis | 7-alpine |
| **Streaming** | Apache Kafka (Confluent) | 7.5.0 |
| **ORM** | SQLAlchemy | 2.0+ |
| **Validation** | Pydantic | 2.4+ |
