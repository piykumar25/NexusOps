"""
NexusOps WebSocket Streaming Service
======================================
Real-time bidirectional communication layer between the frontend and
the agentic orchestration engine.

Protocol:
  Client → Server (JSON):
    { "type": "chat", "session_id": "...", "message": "Why is payment-service down?" }
    { "type": "triage_subscribe", "incident_id": "..." }

  Server → Client (JSON, streamed):
    { "type": "token",       "content": "Based on",  "done": false }
    { "type": "token",       "content": " my analysis", "done": false }
    { "type": "tool_call",   "tool": "ask_k8s_agent", "status": "running" }
    { "type": "tool_result", "tool": "ask_k8s_agent", "result": "..." }
    { "type": "complete",    "content": "...",  "done": true }
    { "type": "triage_update", "stage": "metrics_analysis", "output": "..." }
    { "type": "error",       "message": "..." }
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("nexusops.websocket")

router = APIRouter()

LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "test")


class ConnectionManager:
    """
    Manages active WebSocket connections.
    Supports broadcasting to all connections or targeting specific sessions.
    """

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info(f"WebSocket connected: {session_id} (total: {len(self._connections)})")

    def disconnect(self, session_id: str):
        self._connections.pop(session_id, None)
        logger.info(f"WebSocket disconnected: {session_id} (total: {len(self._connections)})")

    async def send_json(self, session_id: str, data: dict):
        ws = self._connections.get(session_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)

    async def broadcast(self, data: dict):
        disconnected = []
        for sid, ws in self._connections.items():
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(data)
            except Exception:
                disconnected.append(sid)
        for sid in disconnected:
            self.disconnect(sid)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


def _is_real_llm_configured() -> bool:
    """Check if a real LLM (not the test model) is configured."""
    return LLM_MODEL not in ("test", "test:fake", "")


async def _stream_agent_response(websocket: WebSocket, session_id: str, message: str):
    """
    Execute the MasterCoordinator and stream progress updates back to the client.
    Uses the singleton coordinator from main.py when a real LLM is configured.
    Falls back to intelligent mock responses in demo mode.
    """
    try:
        # Signal: thinking started
        await websocket.send_json({
            "type": "status",
            "content": "Analyzing your query...",
            "done": False,
        })

        if _is_real_llm_configured():
            # ── Real LLM Mode ──
            from backend.api.main import get_coordinator
            coordinator = get_coordinator()

            # Signal tool delegation
            for tool_name in coordinator.tools.keys():
                await websocket.send_json({
                    "type": "tool_call",
                    "tool": tool_name,
                    "status": "running",
                })
                await asyncio.sleep(0.2)

            result = await coordinator.run(input_data=message)
            response_text = str(result.output)

            # Signal tool completion
            for tool_name in coordinator.tools.keys():
                await websocket.send_json({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": "complete",
                })
        else:
            # ── Demo Mode (no real LLM) ──
            # Simulate realistic tool execution stages
            demo_tools = ["ask_docs_agent", "ask_k8s_agent", "ask_metrics_agent"]
            for tool_name in demo_tools:
                await websocket.send_json({
                    "type": "tool_call",
                    "tool": tool_name,
                    "status": "running",
                })
                await asyncio.sleep(0.6)  # Simulate agent execution time
                await websocket.send_json({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": "complete",
                })

            response_text = _generate_mock_response(message)

        # Stream response token-by-token
        words = response_text.split(" ")
        for i, word in enumerate(words):
            token = word + " "
            await websocket.send_json({
                "type": "token",
                "content": token,
                "done": False,
            })
            await asyncio.sleep(0.03)  # Simulate LLM generation latency

        # Signal: complete
        await websocket.send_json({
            "type": "complete",
            "content": response_text,
            "done": True,
            "session_id": session_id,
        })

    except Exception as e:
        logger.exception(f"Error streaming response: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })


def _generate_mock_response(message: str) -> str:
    """Generate a realistic mock response for demo mode (no LLM configured)."""
    msg_lower = message.lower()

    if "crash" in msg_lower or "restart" in msg_lower or "pod" in msg_lower or "payment" in msg_lower:
        return (
            "🔍 **Investigation Summary: Pod CrashLoopBackOff**\n\n"
            "I analyzed the payment-service pods across 3 specialist agents:\n\n"
            "---\n\n"
            "**📊 MetricsAgent Findings:**\n"
            "- CPU utilization spiked to **94%** at 15:10 UTC\n"
            "- Memory usage at **98%** of pod limit (1024Mi)\n"
            "- 5xx error rate jumped from 1.2% → **34.5%**\n"
            "- P99 latency degraded from 120ms → **2.8s**\n\n"
            "**🔧 K8sAgent Findings:**\n"
            "- Pod `payment-service-5b4d7-xyz` — **CrashLoopBackOff**\n"
            "- Pod `auth-service-99x-abc` — Running ✅\n"
            "- **7 restarts** in the last hour\n"
            "- Event: `FailedScheduling — Insufficient memory`\n\n"
            "**📚 DocsAgent Findings:**\n"
            "- Runbook `RB-0042` matches: *'Memory leak in payment-service after v2.3 deployment'*\n"
            "- Previous incident `INC-1847` had identical symptoms\n"
            "- Resolution time was 23 minutes via rollback\n\n"
            "---\n\n"
            "**🎯 Root Cause Hypothesis:**\n"
            "The deployment at 14:45 UTC (v2.3.1) introduced a memory leak in the "
            "connection pool handler. Under normal traffic load (~800 rps), memory consumption "
            "grows linearly until the pod hits its 1024Mi limit and gets OOM-killed.\n\n"
            "**⚡ Recommended Actions:**\n"
            "1. **IMMEDIATE:** Rollback to v2.3.0 → `kubectl rollout undo deployment/payment-service`\n"
            "2. **MITIGATE:** Increase memory limit to 2Gi temporarily\n"
            "3. **INVESTIGATE:** Review PR #847 for connection pool changes\n"
            "4. **PREVENT:** Add memory profiling to CI pipeline"
        )

    elif "latency" in msg_lower or "slow" in msg_lower:
        return (
            "🔍 **Investigation Summary: Latency Degradation**\n\n"
            "Elevated P99 latency detected across the auth-service:\n\n"
            "---\n\n"
            "**📊 Metrics:** P99 latency went from 120ms → **3.2s** starting 14:50 UTC\n"
            "**🔧 K8s:** All 3 pods running, but showing increased CPU wait time\n"
            "**📚 Docs:** Runbook `RB-0019` matches — *'Database connection pool saturation'*\n\n"
            "---\n\n"
            "**🎯 Root Cause:** Database connection pool is saturated. "
            "Query `SELECT * FROM sessions` is doing a full table scan after "
            "the index was dropped in migration v45.\n\n"
            "**⚡ Actions:**\n"
            "1. Add index back: `CREATE INDEX idx_sessions_user_id ON sessions(user_id)`\n"
            "2. Increase pool size from 10 → 25\n"
            "3. Add query timeout of 5s to prevent cascade failures"
        )

    elif "memory" in msg_lower or "oom" in msg_lower or "leak" in msg_lower:
        return (
            "🔍 **Investigation Summary: Memory Pressure**\n\n"
            "High memory usage detected across multiple services:\n\n"
            "---\n\n"
            "**📊 MetricsAgent:** Memory utilization at **96%** (982Mi / 1024Mi)\n"
            "**🔧 K8sAgent:** 2 OOMKilled events in the last 30 minutes\n"
            "**📚 DocsAgent:** Runbook `RB-0042` — *'Memory leak triage procedure'*\n\n"
            "---\n\n"
            "**🎯 Root Cause:** Heap analysis shows unbounded cache growth in the "
            "session store. The TTL eviction policy was accidentally disabled in config v2.3.\n\n"
            "**⚡ Actions:**\n"
            "1. Re-enable cache TTL: `session.cache.ttl_seconds=300`\n"
            "2. Trigger manual GC: `kubectl exec -it <pod> -- jcmd 1 GC.run`\n"
            "3. Set memory request/limit ratio to 1:1 to prevent overcommit"
        )

    elif "deploy" in msg_lower or "rollback" in msg_lower:
        return (
            "🔍 **Deployment Analysis**\n\n"
            "Analyzing recent deployment activity:\n\n"
            "---\n\n"
            "**📊 Metrics:** Error rates stable post-deploy ✅\n"
            "**🔧 K8s:** Rolling update completed successfully, all replicas healthy\n"
            "**📚 Docs:** Deployment runbook `RB-0001` followed correctly\n\n"
            "---\n\n"
            "**Status:** The last deployment appears healthy. No anomalies detected.\n\n"
            "If you need a rollback, run:\n"
            "```\nkubectl rollout undo deployment/<service-name> -n production\n```"
        )

    else:
        return (
            "🔍 **NexusOps Analysis**\n\n"
            f"I consulted 3 specialist agents for your query: *\"{message}\"*\n\n"
            "---\n\n"
            "**📚 DocsAgent:** Searched runbooks and incident history — no direct matches\n"
            "**📊 MetricsAgent:** All monitored services within normal parameters\n"
            "**🔧 K8sAgent:** Cluster state healthy, all pods running\n\n"
            "---\n\n"
            "No anomalies detected in the last 30 minutes. "
            "All services are operating within their SLO thresholds.\n\n"
            "💡 *Try asking about a specific service, like:*\n"
            "- *\"Why is the payment-service crashing?\"*\n"
            "- *\"Show me latency trends for auth-service\"*\n"
            "- *\"What happened during incident INC-1847?\"*"
        )


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Primary WebSocket endpoint for the chat interface.
    Handles bidirectional communication with the frontend.
    """
    session_id = str(uuid.uuid4())
    await manager.connect(websocket, session_id)

    # Send welcome message
    await websocket.send_json({
        "type": "connected",
        "session_id": session_id,
        "message": "Connected to NexusOps. How can I help with your infrastructure?",
    })

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
                msg_type = data.get("type", "chat")

                if msg_type == "chat":
                    user_message = data.get("message", "")
                    if user_message.strip():
                        await _stream_agent_response(websocket, session_id, user_message)

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        manager.disconnect(session_id)
