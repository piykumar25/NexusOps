"""
NexusOps PydanticAI Agent Wrapper
===================================
Production-grade wrapper for the pydantic-ai Agent class.
Provides:
  - Tool registration with enable/disable at runtime
  - Retry with exponential backoff for LLM calls
  - Configurable per-agent timeout
  - Version-safe result extraction (pydantic-ai >= 1.70.0)
  - Structured error responses (never crashes the pipeline)
"""

from typing import Any, Callable, Dict, List, Optional
import asyncio
import logging
import inspect
import functools
import datetime
import time

import pydantic_ai
from pydantic_ai import Agent, RunContext, models
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase
from backend.core.agents.agent_base import AgentBase, AgentMetadata, AgentResult, ToolConfig

logger = logging.getLogger("nexusops.agent")


class PydanticAIAgent(AgentBase):
    """
    Production-grade pydantic-ai agent with retry, timeout, and graceful degradation.
    """

    # Default retry and timeout settings (can be overridden per-agent)
    DEFAULT_MAX_RETRIES: int = 3
    DEFAULT_RETRY_BACKOFF: List[float] = [1.0, 2.0, 4.0]  # seconds
    DEFAULT_TIMEOUT_SECONDS: float = 90.0

    def __init__(
        self,
        metadata: AgentMetadata,
        system_prompt: str,
        output_type: Any,
        model_name: str,
        deps_type: Any = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        super().__init__(metadata, output_type, deps_type)
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._pydantic_agent = Agent(
            model=model_name,
            system_prompt=system_prompt,
        )

    def add_tool(self, tool: Callable, name: Optional[str] = None, enabled: bool = True, use_cache: bool = False, return_to_caller: bool = True) -> ToolConfig:
        config = super().add_tool(tool, name, enabled, use_cache, return_to_caller)

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
        """Extract output data from AgentRunResult (version-safe)."""
        if hasattr(result, 'output'):
            return result.output
        if hasattr(result, 'data'):
            return result.data
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

    async def _run_with_retry(self, user_prompt: str, deps: Any, message_history: list) -> Any:
        """
        Execute the pydantic-ai agent with retry + exponential backoff.
        Raises the last exception if all retries are exhausted.
        """
        last_exception = None
        backoff_schedule = self.DEFAULT_RETRY_BACKOFF[:self.max_retries]

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._pydantic_agent.run(
                        user_prompt=user_prompt,
                        deps=deps,
                        message_history=message_history,
                    ),
                    timeout=self.timeout_seconds,
                )
                if attempt > 1:
                    logger.info(f"Agent '{self.metadata.name}' succeeded on attempt {attempt}")
                return result

            except asyncio.TimeoutError:
                last_exception = TimeoutError(
                    f"Agent '{self.metadata.name}' timed out after {self.timeout_seconds}s"
                )
                logger.warning(
                    f"Agent '{self.metadata.name}' timeout on attempt {attempt}/{self.max_retries} "
                    f"({self.timeout_seconds}s)"
                )
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Agent '{self.metadata.name}' failed on attempt {attempt}/{self.max_retries}: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )

            # Backoff before next retry (skip on last attempt)
            if attempt < self.max_retries:
                backoff = backoff_schedule[attempt - 1] if attempt - 1 < len(backoff_schedule) else backoff_schedule[-1]
                logger.info(f"Agent '{self.metadata.name}' retrying in {backoff}s...")
                await asyncio.sleep(backoff)

        # All retries exhausted
        raise last_exception

    async def run(self, input_data: Any, message_history: Optional[MessageHistoryBase] = None, context: Any = None) -> AgentResult:
        """
        Execute the agent with retry, timeout, and structured error handling.
        Never raises — always returns an AgentResult (error results on failure).
        """
        start_time = time.time()

        try:
            framework_messages = message_history.to_framework_messages() if message_history else []

            # Run with retry and timeout
            result = await self._run_with_retry(
                user_prompt=str(input_data),
                deps=context,
                message_history=framework_messages,
            )

            elapsed = time.time() - start_time

            # Extract data using version-safe helpers
            output_data = self._extract_result_data(result)
            usage_data = self._extract_usage(result)
            usage_data["elapsed_seconds"] = round(elapsed, 2)
            usage_data["agent_name"] = self.metadata.name

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

            logger.info(f"Agent '{self.metadata.name}' completed in {elapsed:.2f}s")

            return AgentResult(
                input_data=input_data,
                output=output_data,
                new_messages=new_messages,
                metadata=usage_data,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"Agent '{self.metadata.name}' failed after {self.max_retries} attempts "
                f"in {elapsed:.2f}s. Final error: {e}"
            )
            # Return a graceful error result instead of crashing the pipeline
            error_metadata = {
                "error": str(e),
                "error_type": type(e).__name__,
                "agent_name": self.metadata.name,
                "elapsed_seconds": round(elapsed, 2),
                "retries_exhausted": True,
            }
            return AgentResult(
                input_data=input_data,
                output=f"Agent {self.metadata.name} is temporarily unavailable: {type(e).__name__}",
                new_messages=[UniversalMessage.create(
                    role="assistant",
                    content=f"Error: {str(e)}",
                    metadata=error_metadata,
                )],
                metadata=error_metadata,
            )
