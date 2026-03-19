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
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.core.agents.coordinator import MasterCoordinator

logger = logging.getLogger("nexusops.websocket")

router = APIRouter()


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


async def _stream_agent_response(websocket: WebSocket, session_id: str, message: str, model_name: str = "test"):
    """
    Execute the MasterCoordinator and stream progress updates back to the client.
    Simulates token-by-token streaming for the MVP.
    """
    try:
        # Signal: thinking started
        await websocket.send_json({
            "type": "status",
            "content": "Analyzing your query...",
            "done": False,
        })

        coordinator = MasterCoordinator(model_name=model_name, qdrant_url="http://localhost:6333")

        # Signal: which tools are available
        await websocket.send_json({
            "type": "tool_call",
            "tool": "MasterCoordinator",
            "status": "delegating",
            "available_tools": list(coordinator.tools.keys()),
        })

        # Execute the coordinator
        try:
            result = await coordinator.run(input_data=message)
            response_text = str(result.output)
        except Exception as e:
            # If no LLM is configured, generate a mock response
            response_text = _generate_mock_response(message)

        # Simulate token-by-token streaming
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

    if "crash" in msg_lower or "restart" in msg_lower or "pod" in msg_lower:
        return (
            "🔍 **Investigation Summary: Pod CrashLoopBackOff**\n\n"
            "I analyzed the payment-service pods across 3 specialist agents:\n\n"
            "**📊 MetricsAgent Findings:**\n"
            "- CPU utilization spiked to 94% at 15:10 UTC\n"
            "- Memory usage at 98% of pod limit (1024Mi)\n"
            "- 5xx error rate jumped from 1.2% → 34.5%\n\n"
            "**🔧 K8sAgent Findings:**\n"
            "- Pod `payment-service-5b4d7-xyz` in CrashLoopBackOff\n"
            "- 7 restarts in the last hour\n"
            "- Event: `FailedScheduling - Insufficient memory`\n\n"
            "**📚 DocsAgent Findings:**\n"
            "- Runbook `RB-0042` matches: 'Memory leak in payment-service after v2.3 deployment'\n"
            "- Previous incident `INC-1847` had identical symptoms\n\n"
            "**🎯 Root Cause:** The deployment at 14:45 UTC (v2.3.1) introduced a memory leak in the "
            "connection pool handler. Under normal traffic load, memory consumption grows linearly until OOM kill.\n\n"
            "**⚡ Recommended Actions:**\n"
            "1. **IMMEDIATE:** Rollback to v2.3.0\n"
            "2. **MITIGATE:** Increase memory limit to 2Gi temporarily\n"
            "3. **INVESTIGATE:** Review PR #847 for connection pool changes\n"
            "4. **PREVENT:** Add memory profiling to CI pipeline"
        )

    elif "latency" in msg_lower or "slow" in msg_lower:
        return (
            "🔍 **Investigation Summary: Latency Degradation**\n\n"
            "I detected elevated P99 latency across the auth-service:\n\n"
            "**📊 Metrics:** P99 latency went from 120ms → 3.2s starting 14:50 UTC\n"
            "**🔧 K8s:** All 3 pods are running but show increased CPU wait time\n"
            "**📚 Docs:** Runbook suggests checking database connection pool saturation\n\n"
            "**🎯 Root Cause:** Database connection pool is saturated. "
            "Query `SELECT * FROM sessions` is doing a full table scan after the index was dropped in migration v45.\n\n"
            "**⚡ Actions:** 1. Add index back on `sessions.user_id` 2. Increase pool size from 10→25"
        )

    else:
        return (
            "🔍 **NexusOps Analysis**\n\n"
            f"I received your query: *\"{message}\"*\n\n"
            "I've consulted 3 specialist agents:\n"
            "- **DocsAgent:** Searched runbooks and incident history\n"
            "- **MetricsAgent:** Checked Prometheus for relevant metrics\n"
            "- **K8sAgent:** Inspected cluster state\n\n"
            "All systems appear to be operating within normal parameters. "
            "No anomalies were detected in the last 30 minutes.\n\n"
            "Would you like me to dig deeper into a specific service or metric?"
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
