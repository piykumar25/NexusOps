"""
NexusOps Master Coordinator
=============================
The central orchestration agent. Routes user queries to the right
specialist agents and synthesizes their outputs into a unified response.

Production Features:
  - Partial results: If one agent fails, continue with remaining agents
  - Confidence scoring: Based on how many agents responded successfully
  - Graceful degradation: Never crashes, always returns a useful response
  - Tool timeout isolation: Individual agent failures don't cascade

Agent Delegation Map:
  - DocsAgent    → Runbooks, troubleshooting guides, post-mortems
  - K8sAgent     → Pod status, events, deployments, cluster state
  - MetricsAgent → Prometheus metrics, CPU/memory/latency/error rates
"""

import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata
from backend.core.agents.specialists import DocsAgent, K8sAgent
from backend.core.agents.metrics_agent import MetricsAgent
from pydantic_ai import RunContext

logger = logging.getLogger("nexusops.coordinator")


class NexusOpsOutput(BaseModel):
    """Structured output from the MasterCoordinator."""
    analysis: str = Field(description="The final comprehensive analysis provided to the user")
    confidence: str = Field(description="High/Medium/Low confidence in the analysis")
    specialists_consulted: List[str] = Field(description="List of specialist agents consulted")


class MasterCoordinator(PydanticAIAgent):
    """
    Central orchestrator that receives user queries and delegates
    to the appropriate specialist agents based on intent detection.

    Fault tolerance:
      - Each delegation is wrapped in try/except
      - Partial results returned if some agents fail
      - Confidence adjusted based on successful agent count
    """

    def __init__(self, model_name: str, qdrant_url: str, prometheus_url: str = "http://localhost:9090"):
        metadata = AgentMetadata(
            name="MasterCoordinator",
            description="The central orchestrator for NexusOps. Routes queries to specialist agents and synthesizes their findings.",
        )
        super().__init__(
            metadata=metadata,
            system_prompt="""You are the Master Coordinator of NexusOps — an AI DevOps Operations Center.
Your job is to analyze the user's query, determine which specialist agents to consult, and synthesize a comprehensive answer.

Delegation rules:
- For questions about logs, pods, deployments, or cluster state → delegate to K8sAgent (ask_k8s_agent)
- For questions about runbooks, troubleshooting guides, or past incidents → delegate to DocsAgent (ask_docs_agent)
- For questions about metrics, CPU, memory, latency, or error rates → delegate to MetricsAgent (ask_metrics_agent)
- For complex incidents, consult ALL relevant agents and synthesize their findings.

If an agent returns an error or is unavailable, acknowledge it and work with the data you have from the other agents.
Always provide actionable recommendations with your analysis. Cite your sources (which agent provided each piece of data).""",
            output_type=NexusOpsOutput,
            model_name=model_name,
            timeout_seconds=120.0,  # Coordinator gets extra time since it calls sub-agents
        )

        # Instantiate specialist agents with their own timeouts
        self.docs_agent = DocsAgent(model_name=model_name, qdrant_url=qdrant_url)
        self.k8s_agent = K8sAgent(model_name=model_name)
        self.metrics_agent = MetricsAgent(model_name=model_name, prometheus_url=prometheus_url)
        self._register_delegations()

    def _register_delegations(self):
        """Register delegation tools for each specialist agent with fault-tolerant wrappers."""

        async def ask_docs(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the documentation and runbook agent for troubleshooting guides and past incidents."""
            try:
                from backend.core.agents.specialists import DocsAgentContext
                result = await self.docs_agent.run(query, context=DocsAgentContext(query=query))
                output = str(result.output)
                if result.metadata.get("error"):
                    logger.warning(f"DocsAgent returned with error: {result.metadata.get('error')}")
                    return f"[DocsAgent partial failure] {output}"
                return output
            except Exception as e:
                logger.error(f"DocsAgent delegation failed: {e}")
                return f"[DocsAgent unavailable] Unable to search runbooks: {type(e).__name__}"

        async def ask_k8s(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the Kubernetes agent for pod status, events, and cluster state."""
            try:
                result = await self.k8s_agent.run(query)
                output = str(result.output)
                if result.metadata.get("error"):
                    logger.warning(f"K8sAgent returned with error: {result.metadata.get('error')}")
                    return f"[K8sAgent partial failure] {output}"
                return output
            except Exception as e:
                logger.error(f"K8sAgent delegation failed: {e}")
                return f"[K8sAgent unavailable] Unable to inspect cluster: {type(e).__name__}"

        async def ask_metrics(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the Metrics agent for Prometheus data — CPU, memory, latency, error rates."""
            try:
                result = await self.metrics_agent.run(query)
                output = str(result.output)
                if result.metadata.get("error"):
                    logger.warning(f"MetricsAgent returned with error: {result.metadata.get('error')}")
                    return f"[MetricsAgent partial failure] {output}"
                return output
            except Exception as e:
                logger.error(f"MetricsAgent delegation failed: {e}")
                return f"[MetricsAgent unavailable] Unable to query Prometheus: {type(e).__name__}"

        self.add_tool(ask_docs, name="ask_docs_agent", return_to_caller=True)
        self.add_tool(ask_k8s, name="ask_k8s_agent", return_to_caller=True)
        self.add_tool(ask_metrics, name="ask_metrics_agent", return_to_caller=True)
