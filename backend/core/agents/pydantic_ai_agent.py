"""
NexusOps PydanticAI Agent Wrapper
===================================
Wraps the pydantic-ai Agent class to conform to the AgentBase contract.
Provides tool registration, conversation history bridging, and error handling.

Compatible with pydantic-ai >= 1.70.0
"""

from typing import Any, Callable, Dict, List, Optional
import logging
import inspect
import functools
import datetime

import pydantic_ai
from pydantic_ai import Agent, RunContext, models
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase
from backend.core.agents.agent_base import AgentBase, AgentMetadata, AgentResult, ToolConfig

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

    @staticmethod
    def _extract_result_data(result: Any) -> Any:
        """
        Extract the output data from an AgentRunResult.
        Handles API differences across pydantic-ai versions.
        """
        # pydantic-ai >= 1.70: .output  (preferred)
        if hasattr(result, 'output'):
            return result.output
        # pydantic-ai < 1.0: .data
        if hasattr(result, 'data'):
            return result.data
        # Fallback: .response
        if hasattr(result, 'response'):
            return result.response
        return str(result)

    @staticmethod
    def _extract_usage(result: Any) -> dict:
        """Extract usage info, handling both property and method forms."""
        try:
            usage = result.usage
            if callable(usage):
                usage = usage()
            if usage is None:
                return {}
            if hasattr(usage, 'model_dump'):
                return {"usage": usage.model_dump()}
            if hasattr(usage, 'dict'):
                return {"usage": usage.dict()}
            return {"usage": str(usage)}
        except Exception:
            return {}

    @staticmethod
    def _extract_new_messages(result: Any) -> list:
        """Extract new messages, handling both property and method forms."""
        try:
            msgs = result.new_messages
            if callable(msgs):
                msgs = msgs()
            return list(msgs) if msgs else []
        except Exception:
            return []

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

            # Extract data using version-safe helpers
            output_data = self._extract_result_data(result)
            usage_data = self._extract_usage(result)

            # Map back to UniversalMessages
            new_messages = []
            try:
                raw_msgs = self._extract_new_messages(result)
                for _ in raw_msgs:
                    new_messages.append(UniversalMessage.create(
                        role="assistant",
                        content=str(output_data),
                        metadata=usage_data,
                    ))
            except Exception:
                new_messages = [UniversalMessage.create(role="assistant", content=str(output_data))]

            if not new_messages:
                new_messages = [UniversalMessage.create(role="assistant", content=str(output_data))]

            return AgentResult(
                input_data=input_data,
                output=output_data,
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
