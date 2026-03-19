from typing import Any, Dict, List
from pydantic import BaseModel, Field
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata
from backend.core.agents.specialists import DocsAgent, K8sAgent

class nexusopsOutput(BaseModel):
    analysis: str = Field(description="The final comprehensive analysis provided to the user")
    confidence: str = Field(description="High/Medium/Low confidence in the analysis")
    specialists_consulted: List[str] = Field(description="List of specialist agents consulted")

class MasterCoordinator(PydanticAIAgent):
    def __init__(self, model_name: str, qdrant_url: str):
        metadata = AgentMetadata(name="MasterCoordinator", description="The central orchestrator for the AI DevOps Ops Center.")
        super().__init__(
            metadata=metadata,
            system_prompt="""You are the Master Coordinator of the AI DevOps Ops Center. 
            Your job is to route user queries to the right specialist agents.
            If the query is about logs, metrics, or K8s, delegate to the K8sAgent.
            If the query is about runbooks, troubleshooting guides, or procedures, delegate to the DocsAgent. 
            Synthesize their answers into a final response.""",
            output_type=nexusopsOutput,
            model_name=model_name
        )
        # Instantiate specialists
        self.docs_agent = DocsAgent(model_name=model_name, qdrant_url=qdrant_url)
        self.k8s_agent = K8sAgent(model_name=model_name)
        self._register_delegations()

    def _register_delegations(self):
        async def ask_docs(query: str) -> str:
            """Query the documentation and runbook agent."""
            # Use a dummy context for now
            from backend.core.agents.specialists import DocsAgentContext
            result = await self.docs_agent.run(query, context=DocsAgentContext(query=query))
            return str(result.output)
            
        async def ask_k8s(query: str) -> str:
            """Query the Kubernetes agent for operational state."""
            result = await self.k8s_agent.run(query)
            return str(result.output)

        self.add_tool(ask_docs, name="ask_docs_agent", return_to_caller=True)
        self.add_tool(ask_k8s, name="ask_k8s_agent", return_to_caller=True)
