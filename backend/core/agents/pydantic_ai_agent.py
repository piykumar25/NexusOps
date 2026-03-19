"""
NexusOps PydanticAI Agent Wrapper
===================================
Wraps the pydantic-ai Agent class to conform to the AgentBase contract.
Provides tool registration, conversation history bridging, and error handling.
"""

from typing import Any, Callable, Dict, List, Optional
import logging
import pydantic_ai
from pydantic_ai import Agent, RunContext, models
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase
from backend.core.agents.agent_base import AgentBase, AgentMetadata, AgentResult, ToolConfig
import datetime
import functools

logger = logging.getLogger("nexusops.agent")


class PydanticAIAgent(AgentBase):
    def __init__(self, metadata: AgentMetadata, system_prompt: str, output_type: Any, model_name: str, deps_type: Any = None):
        super().__init__(metadata, output_type, deps_type)
        self._pydantic_agent = Agent(
            model=model_name,
            system_prompt=system_prompt,
        )

    def add_tool(self, tool: Callable, name: Optional[str] = None, enabled: bool = True, use_cache: bool = False, return_to_caller: bool = True) -> ToolConfig:
        config = super().add_tool(tool, name, enabled, use_cache, return_to_caller)

        # Wrap tool to check enabled flag at runtime
        @functools.wraps(tool)
        async def _tool_wrapper(*args, **kwargs):
            if not self.tools[config.name].enabled:
                raise RuntimeError(f"Tool {config.name} is currently disabled.")
            return await tool(*args, **kwargs) if inspect.iscoroutinefunction(tool) else tool(*args, **kwargs)

        if return_to_caller:
            self._pydantic_agent.tool(name=config.name)(_tool_wrapper)
        else:
            self._pydantic_agent.system_prompt(f"Use output tool {config.name} to return final result.")
            self._pydantic_agent.tool(name=config.name)(_tool_wrapper)

        return config

    async def run(self, input_data: Any, message_history: Optional[MessageHistoryBase] = None, context: Any = None) -> AgentResult:
        """Execute the agent with full error handling and graceful degradation."""
        try:
            # Convert history if provided
            framework_messages = message_history.to_framework_messages() if message_history else []

            # Run Pydantic AI
            result = await self._pydantic_agent.run(
                user_prompt=str(input_data),
                deps=context,
                message_history=framework_messages,
            )

            # Map back to UniversalMessages
            new_messages = []
            try:
                for msg in result.new_messages():
                    new_messages.append(UniversalMessage.create(
                        role="assistant",
                        content=str(result.data),
                        metadata={"usage": result.usage().model_dump()} if result.usage() else {},
                    ))
            except Exception:
                # If message mapping fails, still return the result
                new_messages = [UniversalMessage.create(role="assistant", content=str(result.data))]

            usage_data = {}
            try:
                if result.usage():
                    usage_data = {"usage": result.usage().model_dump()}
            except Exception:
                pass

            return AgentResult(
                input_data=input_data,
                output=result.data,
                new_messages=new_messages,
                metadata=usage_data,
            )

        except Exception as e:
            logger.error(f"Agent '{self.metadata.name}' failed on input: {str(input_data)[:200]}. Error: {e}")
            # Return a graceful error result instead of crashing the pipeline
            return AgentResult(
                input_data=input_data,
                output=f"Agent {self.metadata.name} encountered an error: {str(e)}",
                new_messages=[UniversalMessage.create(
                    role="assistant",
                    content=f"Error: {str(e)}",
                    metadata={"error": True, "agent_name": self.metadata.name},
                )],
                metadata={"error": str(e)},
            )
