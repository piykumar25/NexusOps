# NexusOps — Local Testing Guide

> How to run, test, and debug NexusOps on your local machine

---

## Quick Start (30 seconds)

If you just want to see the app running immediately:

```powershell
# 1. Start infrastructure
docker compose up -d

# 2. Start backend (demo mode — no LLM needed)
.\.venv\Scripts\Activate.ps1
uvicorn backend.api.main:app --host 0.0.0.0 --port 8082 --reload

# 3. Start frontend
cd frontend && npm run dev
```

Open http://localhost:3000 — you'll see the full UI with demo responses.

---

## Running Modes

### Demo Mode (Default)

No LLM required. The backend returns realistic pre-built responses.

```powershell
$env:LLM_MODEL_NAME = "test"
uvicorn backend.api.main:app --host 0.0.0.0 --port 8082 --reload
```

**Best for:** Portfolio demos, frontend development, CI pipelines.

### Ollama Mode (Real AI)

Requires Ollama installed with a pulled model.

```powershell
# Install Ollama: https://ollama.ai
# In a separate terminal:
ollama pull llama3.2:3b    # 2GB, fast
# OR
ollama pull llama3.1       # 4.9GB, smarter

# Start backend
$env:OLLAMA_BASE_URL = "http://localhost:11434/v1"
$env:LLM_MODEL_NAME = "ollama:llama3.2:3b"
uvicorn backend.api.main:app --host 0.0.0.0 --port 8082 --reload
```

**Best for:** Testing real agent orchestration and LLM tool calling.

> **Tip:** If `ollama` is not recognized in your VS Code terminal, open a fresh PowerShell from the Start Menu. The PATH was updated when Ollama was installed but existing terminals don't pick it up automatically.

---

## Infrastructure Services

### Start All Services

```powershell
docker compose up -d
```

### Check Service Health

```powershell
# All services
docker compose ps

# Individual checks
docker exec nexusops-postgres pg_isready -U nexusops       # PostgreSQL
docker exec nexusops-redis redis-cli ping                    # Redis
curl http://localhost:6333/readyz                             # Qdrant
curl http://localhost:9093                                     # Kafka (connection test)
```

### Reset Everything

```powershell
docker compose down -v    # Stops and DELETES all data volumes
docker compose up -d      # Fresh start
```

### Service Ports

| Service | Port | Dashboard |
|---------|------|-----------|
| PostgreSQL | 5432 | — |
| Redis | 6379 | — |
| Qdrant | 6333 | http://localhost:6333/dashboard |
| Kafka | 9093 | — |
| Zookeeper | 22181 | — |

---

## Running Tests

### Unit Tests

```powershell
.\.venv\Scripts\Activate.ps1

# Agent framework tests
python -m pytest test_agent.py -v

# Phase 2 integration tests (Kafka, webhooks)
python -m pytest test_phase2.py -v

# All tests
python -m pytest -v
```

### API Endpoint Tests

```powershell
# Health check
curl http://localhost:8082/health

# REST chat (requires running backend)
curl -X POST http://localhost:8082/api/chat `
  -H "Content-Type: application/json" `
  -d '{"message": "Why is the payment-service crashing?", "session_id": "test-123"}'
```

### WebSocket Test (Python)

```python
import asyncio
import websockets
import json

async def test_ws():
    async with websockets.connect("ws://localhost:8082/ws/chat") as ws:
        # Receive connection message
        msg = await ws.recv()
        print("Connected:", json.loads(msg))

        # Send a query
        await ws.send(json.dumps({
            "type": "chat",
            "message": "Why is the payment-service crashing?"
        }))

        # Receive streamed response
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if data["type"] == "token":
                print(data["content"], end="", flush=True)
            elif data["type"] == "complete":
                print("\n\nDone!")
                break

asyncio.run(test_ws())
```

Save as `/tmp/test_ws.py` and run:
```powershell
python /tmp/test_ws.py
```

---

## Debugging

### Backend Logs

Uvicorn with `--reload` shows all logs in the terminal. Key log prefixes:

| Logger | What it shows |
|--------|--------------|
| `nexusops.api` | Startup, shutdown, coordinator init |
| `nexusops.websocket` | WebSocket connections, disconnections |
| `nexusops.agent` | Agent execution, errors, tool calls |
| `nexusops.kafka` | Topic management, producer/consumer activity |
| `nexusops.rag` | RAG retrieval, embedding service status |
| `httpx` | Outgoing HTTP requests (LLM calls to Ollama) |

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `uvicorn not recognized` | Virtual env not activated | `.\.venv\Scripts\Activate.ps1` |
| `ollama not recognized` | PATH not refreshed | Open a new terminal |
| `OLLAMA_BASE_URL not set` | Missing env var | `$env:OLLAMA_BASE_URL = "http://localhost:11434/v1"` |
| `model 'X' not found` | Model not pulled | `ollama pull <model>` from fresh terminal |
| `WebSocket error: [object Event]` | Backend restarting | Normal during dev, auto-reconnects |
| `Qdrant version mismatch` | Client/server minor version diff | Harmless warning, ignore |
| `RAG retrieval failed` | Embedding service not running | Expected in dev, returns empty results |
| `Application startup failed` | Missing env var or dependency | Check the full traceback |

### Swagger UI

FastAPI auto-generates API documentation at:
- **Swagger:** http://localhost:8082/docs
- **ReDoc:** http://localhost:8082/redoc

---

## Frontend Development

### Dev Server

```powershell
cd frontend
npm run dev
```

Runs on http://localhost:3000 with hot-reload via Turbopack.

### Key Files

| File | Purpose |
|------|---------|
| `src/app/page.tsx` | Main operations console UI |
| `src/app/layout.tsx` | Root layout, fonts, metadata |
| `src/hooks/useNexusWebSocket.ts` | Auto-reconnect WebSocket hook |
| `src/app/globals.css` | Global styles, dark theme |

### WebSocket Hook Usage

```tsx
const { messages, sendMessage, isConnected } = useNexusWebSocket();

// Send a message
sendMessage("Why is the payment-service crashing?");

// Messages stream in automatically via the hook
```

---

## Performance Notes

| Model | Size | Approx. Response Time | Quality |
|-------|------|----------------------|---------|
| `test` (demo) | 0 | Instant | Pre-built templates |
| `llama3.2:3b` | 2GB | 10-20s | Good for common queries |
| `llama3.1` | 4.9GB | 30-60s | Best reasoning quality |

> Response time depends heavily on your hardware. GPU acceleration makes a significant difference with Ollama.

---

## Docker-Only Deployment

To run the entire stack in Docker (future):

```powershell
# Build backend image
docker build -t nexusops-backend ./backend

# Run everything
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
