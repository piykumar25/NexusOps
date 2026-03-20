"""
NexusOps Specialist Agents
============================
Production-grade specialist agents for DevOps operations.

DocsAgent  → RAG-powered runbook and incident documentation search
K8sAgent   → Real Kubernetes cluster inspection (read-only)

Both agents include graceful degradation:
  - K8sAgent: Falls back to simulated data if no kubeconfig is available
  - DocsAgent: Returns "no results found" if Qdrant or embeddings are down
"""

import json
import logging
import os
from typing import Any, List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from backend.core.agents.agent_base import AgentMetadata
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.utils.rag_utils import DocumentRetriever

logger = logging.getLogger("nexusops.specialists")


# ─── DocsAgent ───────────────────────────────────────────────────────────────

class DocsAgentOutput(BaseModel):
    answer: str = Field(description="The comprehensive answer based on retrieved documents")
    sources: List[str] = Field(description="List of document chunks/titles used to formulate the answer")


class DocsAgentContext(BaseModel):
    query: str


class DocsAgent(PydanticAIAgent):
    """RAG-powered documentation and runbook search agent."""

    def __init__(self, model_name: str, qdrant_url: str):
        metadata = AgentMetadata(
            name="DocsAgent",
            description="Searches runbooks and incident documentation to answer operations questions.",
        )
        super().__init__(
            metadata=metadata,
            system_prompt=(
                "You are an expert DevOps engineer answering questions based ONLY on the provided runbooks "
                "and incident documentation. If the search returns no results, acknowledge that and suggest "
                "the user check their documentation repository. Always cite your sources."
            ),
            output_type=DocsAgentOutput,
            model_name=model_name,
            deps_type=DocsAgentContext,
            timeout_seconds=60.0,
        )
        self.retriever = DocumentRetriever(qdrant_url=qdrant_url)
        self._register_tools()

    def _register_tools(self):
        async def search_runbooks(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Search for relevant runbooks, incident post-mortems, and troubleshooting guides."""
            try:
                docs = self.retriever.retrieve(query)
                if not docs:
                    return "No relevant runbooks or documentation found for this query."
                return json.dumps([
                    {"text": d.get("content", ""), "score": round(d.get("score", 0), 3), "metadata": d.get("metadata", {})}
                    for d in docs
                ], indent=2)
            except Exception as e:
                logger.error(f"search_runbooks failed: {e}")
                return f"Documentation search temporarily unavailable: {type(e).__name__}"

        self.add_tool(search_runbooks, name="search_runbooks", return_to_caller=True)


# ─── K8sAgent ────────────────────────────────────────────────────────────────

class K8sAgentOutput(BaseModel):
    finding: str = Field(description="Analysis of the Kubernetes resource state")
    actions_taken: List[str] = Field(description="Read-only actions taken against the cluster")


class K8sAgent(PydanticAIAgent):
    """
    Kubernetes cluster inspection agent (read-only).
    Connects to a real cluster via kubeconfig when available,
    falls back to simulated data otherwise.
    """

    def __init__(self, model_name: str):
        metadata = AgentMetadata(
            name="K8sAgent",
            description="Interacts with a Kubernetes cluster (read-only) to inspect pods, deployments, and events.",
        )
        super().__init__(
            metadata=metadata,
            system_prompt=(
                "You are a Kubernetes administrator with read-only access. "
                "Analyze the cluster state, identify unhealthy resources, and provide "
                "actionable recommendations. You cannot make changes to the cluster."
            ),
            output_type=K8sAgentOutput,
            model_name=model_name,
            timeout_seconds=60.0,
        )
        self._k8s_available = False
        self._v1 = None
        self._init_k8s_client()
        self._register_tools()

    def _init_k8s_client(self):
        """Try to initialize the Kubernetes client. Falls back to simulated mode if unavailable."""
        try:
            from kubernetes import client, config

            # Try in-cluster config first (for running inside K8s), then kubeconfig
            try:
                config.load_incluster_config()
                logger.info("K8sAgent: Using in-cluster Kubernetes config")
            except config.ConfigException:
                config.load_kube_config()
                logger.info("K8sAgent: Using kubeconfig file")

            self._v1 = client.CoreV1Api()
            self._k8s_available = True
            logger.info("K8sAgent: Kubernetes client initialized successfully")
        except ImportError:
            logger.warning("K8sAgent: 'kubernetes' package not installed — using simulated data")
        except Exception as e:
            logger.warning(f"K8sAgent: Kubernetes client unavailable ({e}) — using simulated data")

    def _register_tools(self):
        async def get_pods(ctx: RunContext[Any], namespace: str = "default", **kwargs) -> str:
            """Get pods and their status in a given namespace."""
            if self._k8s_available and self._v1:
                return await self._real_get_pods(namespace)
            return self._simulated_get_pods(namespace)

        async def get_events(ctx: RunContext[Any], namespace: str = "default", **kwargs) -> str:
            """Get recent Kubernetes events for a namespace."""
            if self._k8s_available and self._v1:
                return await self._real_get_events(namespace)
            return self._simulated_get_events(namespace)

        self.add_tool(get_pods, name="get_pods", return_to_caller=True)
        self.add_tool(get_events, name="get_events", return_to_caller=True)

    async def _real_get_pods(self, namespace: str) -> str:
        """Fetch real pod data from the Kubernetes cluster."""
        try:
            import asyncio
            pods = await asyncio.to_thread(
                self._v1.list_namespaced_pod, namespace=namespace
            )

            pod_list = []
            for pod in pods.items:
                container_statuses = []
                restarts = 0

                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        container_statuses.append({
                            "name": cs.name,
                            "ready": cs.ready,
                            "restart_count": cs.restart_count,
                            "state": (
                                "Running" if cs.state.running else
                                "Waiting" if cs.state.waiting else
                                "Terminated" if cs.state.terminated else "Unknown"
                            ),
                        })
                        restarts += cs.restart_count

                pod_list.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "restarts": restarts,
                    "containers": container_statuses,
                    "node": pod.spec.node_name,
                    "created": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
                })

            return json.dumps({"pods": pod_list, "total": len(pod_list)}, indent=2)

        except Exception as e:
            logger.error(f"Real get_pods failed: {e}")
            return f"Error fetching pods: {type(e).__name__}: {str(e)}"

    async def _real_get_events(self, namespace: str) -> str:
        """Fetch real events from the Kubernetes cluster."""
        try:
            import asyncio
            events = await asyncio.to_thread(
                self._v1.list_namespaced_event, namespace=namespace
            )

            # Sort by last timestamp, take latest 20
            sorted_events = sorted(
                events.items,
                key=lambda e: e.last_timestamp or e.metadata.creation_timestamp or "",
                reverse=True,
            )[:20]

            event_list = []
            for event in sorted_events:
                event_list.append({
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                    "count": event.count,
                    "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None,
                })

            return json.dumps({"events": event_list, "total": len(event_list)}, indent=2)

        except Exception as e:
            logger.error(f"Real get_events failed: {e}")
            return f"Error fetching events: {type(e).__name__}: {str(e)}"

    def _simulated_get_pods(self, namespace: str) -> str:
        """Simulated pod data for demo mode or when K8s is unavailable."""
        return json.dumps({
            "pods": [
                {"name": "payment-service-5b4d7-xyz", "phase": "CrashLoopBackOff", "restarts": 7,
                 "containers": [{"name": "payment", "ready": False, "restart_count": 7, "state": "Waiting"}]},
                {"name": "payment-service-5b4d7-abc", "phase": "Running", "restarts": 0,
                 "containers": [{"name": "payment", "ready": True, "restart_count": 0, "state": "Running"}]},
                {"name": "auth-service-99x-abc", "phase": "Running", "restarts": 0,
                 "containers": [{"name": "auth", "ready": True, "restart_count": 0, "state": "Running"}]},
                {"name": "order-service-2c3d4-def", "phase": "Running", "restarts": 1,
                 "containers": [{"name": "order", "ready": True, "restart_count": 1, "state": "Running"}]},
            ],
            "total": 4,
            "source": "simulated",
        }, indent=2)

    def _simulated_get_events(self, namespace: str) -> str:
        """Simulated events for demo mode or when K8s is unavailable."""
        return json.dumps({
            "events": [
                {"type": "Warning", "reason": "FailedScheduling", "message": "Insufficient memory",
                 "object": "Pod/payment-service-5b4d7-xyz", "count": 5},
                {"type": "Warning", "reason": "BackOff", "message": "Back-off restarting failed container",
                 "object": "Pod/payment-service-5b4d7-xyz", "count": 7},
                {"type": "Normal", "reason": "Pulling", "message": "Pulling image payment-service:v2.3.1",
                 "object": "Pod/payment-service-5b4d7-xyz", "count": 8},
                {"type": "Normal", "reason": "Scheduled", "message": "Successfully assigned to node-3",
                 "object": "Pod/auth-service-99x-abc", "count": 1},
            ],
            "total": 4,
            "source": "simulated",
        }, indent=2)
