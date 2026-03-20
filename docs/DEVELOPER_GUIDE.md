# NexusOps — Developer Guide

> Everything you need to contribute to NexusOps

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.11+ | Backend runtime |
| **Node.js** | 18+ | Frontend runtime |
| **Docker Desktop** | Latest | Infrastructure services |
| **Ollama** | Latest | Local LLM inference |
| **Git** | 2.30+ | Version control |

---

## Project Setup

### 1. Clone & Install Backend

```powershell
git clone https://github.com/piykumar25/NexusOps.git
cd NexusOps

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate      # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 2. Install Frontend

```powershell
cd frontend
npm install
cd ..
```

### 3. Start Infrastructure

```powershell
docker compose up -d
```

This starts: PostgreSQL (`:5432`), Redis (`:6379`), Qdrant (`:6333`), Kafka (`:9093`), Zookeeper (`:22181`)

### 4. Install & Configure Ollama

```powershell
# Install from https://ollama.ai
ollama pull llama3.2:3b       # Lightweight (2GB, fast)
ollama pull llama3.1           # Full-size (4.9GB, smarter)
```

### 5. Run the Application

**Terminal 1 — Backend:**
```powershell
.\.venv\Scripts\Activate.ps1
$env:OLLAMA_BASE_URL = "http://localhost:11434/v1"
$env:LLM_MODEL_NAME = "ollama:llama3.2:3b"
uvicorn backend.api.main:app --host 0.0.0.0 --port 8082 --reload
```

**Terminal 2 — Frontend:**
```powershell
cd frontend
npm run dev
```

**Open:** http://localhost:3000

---

## Environment Variables & Multi-Tenancy (Tier 3)

The application utilizes strict Pydantic validation via `NexusOpsSettings`. Deployment variables are managed exclusively via the `.env` file instead of inline scripts.

| Variable | Default (Local) | Description |
|----------|---------|-------------|
| `LLM_MODEL_NAME` | `test` | AI model identifier. Use `test` for demo mode bypass, `ollama:llama3.2:3b` for real AI orchestration |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Local deployment endpoint for Ollama backend |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9093` | Kafka broker address |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant vector database connection endpoint |
| `PROMETHEUS_URL` | `http://localhost:9090` | Timeseries database URL |
| `DATABASE_URL` | `postgresql://nexusops...` | PostgreSQL connection string |
| `GUARDRAIL_ENABLE_INJECTION_FILTER` | `true` | Security toggle (Tier 1) |

> Copy `.env.example` to `.env` immediately after repository clone to establish baseline connections.

---

## Managing Database Migrations (Tier 4)

NexusOps persists Conversation histories using `SQLAlchemy`. All database schema iterations are tracked centrally:
```powershell
# Ensure DB is running
docker compose up -d postgres

# Execute all pending migrations
alembic upgrade head
```
When altering `backend/core/db/models.py`, generate a new migration via `alembic revision --autogenerate -m "description"`.

---

## Adding a New Specialist Agent

Follow this pattern to add a new agent (e.g., `LogsAgent`):

### Step 1: Define the Agent

Create `backend/core/agents/logs_agent.py`:

```python
from typing import Any, List
from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata


class LogsAgentOutput(BaseModel):
    findings: str = Field(description="Log analysis findings")
    log_entries: List[str] = Field(description="Relevant log entries")


class LogsAgent(PydanticAIAgent):
    def __init__(self, model_name: str):
        metadata = AgentMetadata(
            name="LogsAgent",
            description="Searches application logs for errors and patterns."
        )
        super().__init__(
            metadata=metadata,
            system_prompt="You are a log analysis expert. Search and analyze application logs.",
            output_type=LogsAgentOutput,
            model_name=model_name,
        )
        self._register_tools()

    def _register_tools(self):
        async def search_logs(ctx: RunContext[Any], query: str, service: str = "all", **kwargs) -> str:
            """Search application logs for a given query."""
            # Your implementation here
            return f"Found 3 ERROR entries for {service} matching '{query}'"

        self.add_tool(search_logs, name="search_logs", return_to_caller=True)
```

### Step 2: Register in the Coordinator

In `backend/core/agents/coordinator.py`:

```python
# 1. Import
from backend.core.agents.logs_agent import LogsAgent

# 2. Initialize in __init__
self.logs_agent = LogsAgent(model_name=model_name)

# 3. Add delegation tool in _register_delegations()
async def ask_logs(ctx: RunContext[Any], query: str, **kwargs) -> str:
    """Query the Logs agent for application log analysis."""
    result = await self.logs_agent.run(query)
    return str(result.output)

self.add_tool(ask_logs, name="ask_logs_agent", return_to_caller=True)

# 4. Update the system prompt to mention the new agent
```

### Step 3: Update the System Prompt

Add a line to the coordinator's system prompt:
```
- For questions about application logs, errors, or stack traces → delegate to LogsAgent (ask_logs_agent)
```

---

## Key Design Patterns

### 1. Singleton Coordinator
The `MasterCoordinator` is created once at startup via `get_coordinator()` in `main.py`. This avoids expensive re-initialization per request.

### 2. Version-Safe pydantic-ai Wrapper
`PydanticAIAgent._extract_result_data()` handles API differences across pydantic-ai versions (`.output` vs `.data` vs `.response`).

### 3. Graceful Degradation
- **RAG Retriever:** Returns empty results if Qdrant or embedding service is down
- **Agent Errors:** Return error messages instead of crashing the pipeline
- **Kafka:** Startup continues if the broker is unreachable

### 4. Demo Mode
When `LLM_MODEL_NAME=test`, the WebSocket handler bypasses the real agent pipeline and returns pre-built markdown responses. This enables portfolio demos without GPU resources.

### 5. Dead Letter Queue
Failed Kafka messages are automatically routed to `nexusops-dlq` with error metadata for debugging.

---

## Code Style

| Aspect | Convention |
|--------|-----------|
| Python naming | PEP 8 (`snake_case` functions, `PascalCase` classes) |
| Type hints | Required on all public functions |
| Docstrings | Required on all classes and public methods |
| Logging | Use `logging.getLogger("nexusops.<module>")` |
| Error handling | Catch and log, return graceful defaults |
| Pydantic models | Use `Field(description=...)` on all fields |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service info |
| `GET` | `/health` | Health check with loaded agents |
| `GET` | `/docs` | Swagger UI (auto-generated) |
| `POST` | `/api/chat` | REST chat endpoint |
| `WS` | `/ws/chat` | WebSocket streaming chat |
| `POST` | `/webhooks/github` | GitHub webhook ingestion |
| `POST` | `/webhooks/pagerduty` | PagerDuty webhook ingestion |
| `POST` | `/webhooks/datadog` | Datadog webhook ingestion |

---

## Git Workflow

```powershell
# Feature branch
git checkout -b feature/logs-agent

# Make changes, then:
git add -A
git commit -m "feat: add LogsAgent for application log analysis"
git push origin feature/logs-agent

# Open PR on GitHub
```

### Commit Message Convention

| Prefix | Usage |
|--------|-------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `refactor:` | Code restructure (no behavior change) |
| `docs:` | Documentation only |
| `test:` | Adding or updating tests |
| `chore:` | Build/config changes |
