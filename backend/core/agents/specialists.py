from typing import Any, List, Optional
from pydantic import BaseModel, Field
from backend.core.agents.pydantic_ai_agent import PydanticAIAgent
from backend.core.agents.agent_base import AgentMetadata
from backend.core.utils.rag_utils import DocumentRetriever, RetrieverConfig
from backend.core.utils.rag_utils import DocumentRetriever, RetrieverConfig
import json
from pydantic_ai import RunContext

class DocsAgentOutput(BaseModel):
    answer: str = Field(description="The comprehensive answer based on retrieved documents")
    sources: List[str] = Field(description="List of document chunks/titles used to formulate the answer")

class DocsAgentContext(BaseModel):
    query: str
    
class DocsAgent(PydanticAIAgent):
    def __init__(self, model_name: str, qdrant_url: str):
        metadata = AgentMetadata(name="DocsAgent", description="Searches runbooks and incident documentation to answer operations questions.")
        super().__init__(
            metadata=metadata,
            system_prompt="You are an expert DevOps engineer answering questions based ONLY on the provided runbooks. Cite your sources.",
            output_type=DocsAgentOutput,
            model_name=model_name,
            deps_type=DocsAgentContext
        )
        self.retriever = DocumentRetriever(RetrieverConfig(qdrant_url=qdrant_url))
        self._register_tools()

    def _register_tools(self):
        async def search_runbooks(ctx: RunContext[Any], query: str, **kwargs) -> str:
            """Search for relevant runbooks or incident post-mortems."""
            docs = self.retriever.retrieve(query)
            if not docs:
                return "No relevant runbooks found."
            return json.dumps([{"text": d.content, "meta": d.metadata} for d in docs])
            
        self.add_tool(search_runbooks, name="search_runbooks", return_to_caller=True)

class K8sAgentOutput(BaseModel):
    finding: str = Field(description="Analysis of the Kubernetes resource state")
    actions_taken: List[str] = Field(description="Read-only actions taken against the cluster")

class K8sAgent(PydanticAIAgent):
    def __init__(self, model_name: str):
        metadata = AgentMetadata(name="K8sAgent", description="Interacts with a Kubernetes cluster (read-only) to inspect pods, deployments, and events.")
        super().__init__(
            metadata=metadata,
            system_prompt="You are a K8s administrator. Analyze the cluster state. You only have read access.",
            output_type=K8sAgentOutput,
            model_name=model_name
        )
        self._register_tools()

    def _register_tools(self):
        async def get_pods(ctx: RunContext[Any], namespace: str = "default", **kwargs) -> str:
            """Get pods in a namespace (simulated)."""
            return f"Simulated pods in {namespace}: payment-service-5b4d7-xyz (CrashLoopBackOff), auth-service-99x-abc (Running)"
            
        async def get_events(ctx: RunContext[Any], namespace: str = "default", **kwargs) -> str:
            """Get recent K8s events (simulated)."""
            return f"Simulated events in {namespace}: Warning FailedScheduling payment-service Insufficient memory"
            
        self.add_tool(get_pods, name="get_pods", return_to_caller=True)
        self.add_tool(get_events, name="get_events", return_to_caller=True)
