"""
NexusOps Master Coordinator
=============================
The central orchestration agent. Routes user queries to the right
specialist agents and synthesizes their outputs into a unified response.

Agent Delegation Map:
  - DocsAgent    → Runbooks, troubleshooting guides, post-mortems
  - K8sAgent     → Pod status, events, deployments, cluster state
  - MetricsAgent → Prometheus metrics, CPU/memory/latency/error rates
"""

from typing import Any, Dict, List
from pydantic import BaseModel, Field
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata
from backend.core.agents.specialists import DocsAgent, K8sAgent
from backend.core.agents.metrics_agent import MetricsAgent
from pydantic_ai import RunContext


class NexusOpsOutput(BaseModel):
    """Structured output from the MasterCoordinator."""
    analysis: str = Field(description="The final comprehensive analysis provided to the user")
    confidence: str = Field(description="High/Medium/Low confidence in the analysis")
    specialists_consulted: List[str] = Field(description="List of specialist agents consulted")


class MasterCoordinator(PydanticAIAgent):
    """
    Central orchestrator that receives user queries and delegates
    to the appropriate specialist agents based on intent detection.
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

Always provide actionable recommendations with your analysis.""",
            output_type=NexusOpsOutput,
            model_name=model_name,
        )

        # Instantiate specialist agents
        self.docs_agent = DocsAgent(model_name=model_name, qdrant_url=qdrant_url)
        self.k8s_agent = K8sAgent(model_name=model_name)
        self.metrics_agent = MetricsAgent(model_name=model_name, prometheus_url=prometheus_url)
        self._register_delegations()

    def _register_delegations(self):
        """Register delegation tools for each specialist agent."""

        async def ask_docs(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the documentation and runbook agent for troubleshooting guides and past incidents."""
            from backend.core.agents.specialists import DocsAgentContext
            result = await self.docs_agent.run(query, context=DocsAgentContext(query=query))
            return str(result.output)

        async def ask_k8s(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the Kubernetes agent for pod status, events, and cluster state."""
            result = await self.k8s_agent.run(query)
            return str(result.output)

        async def ask_metrics(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Query the Metrics agent for Prometheus data — CPU, memory, latency, error rates."""
            result = await self.metrics_agent.run(query)
            return str(result.output)

        self.add_tool(ask_docs, name="ask_docs_agent", return_to_caller=True)
        self.add_tool(ask_k8s, name="ask_k8s_agent", return_to_caller=True)
        self.add_tool(ask_metrics, name="ask_metrics_agent", return_to_caller=True)
