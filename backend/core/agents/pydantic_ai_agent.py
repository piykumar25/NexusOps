from typing import Any, Callable, Dict, List, Optional
import pydantic_ai
from pydantic_ai import Agent, RunContext, models
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase
from backend.core.agents.agent_base import AgentBase, AgentMetadata, AgentResult, ToolConfig
import datetime

class PydanticAIAgent(AgentBase):
    def __init__(self, metadata: AgentMetadata, system_prompt: str, output_type: Any, model_name: str, deps_type: Any = None):
        super().__init__(metadata, output_type, deps_type)
        # Provide the model directly to Agent, which handles inference
        self._pydantic_agent = Agent(
            model=model_name,
            system_prompt=system_prompt
        )

    def add_tool(self, tool: Callable, name: Optional[str] = None, enabled: bool = True, use_cache: bool = False, return_to_caller: bool = True) -> ToolConfig:
        config = super().add_tool(tool, name, enabled, use_cache, return_to_caller)
        
        # Wrap tool to check enabled flag at runtime
        async def _tool_wrapper(ctx: RunContext[Any], *args, **kwargs):
            if not self.tools[config.name].enabled:
                raise RuntimeError(f"Tool {config.name} is currently disabled.")
            # Simple check if tool expects RunContext
            import inspect
            sig = inspect.signature(tool)
            if list(sig.parameters.values())[0].annotation == RunContext[Any] or 'ctx' in sig.parameters:
                return await tool(ctx, *args, **kwargs) if inspect.iscoroutinefunction(tool) else tool(ctx, *args, **kwargs)
            return await tool(*args, **kwargs) if inspect.iscoroutinefunction(tool) else tool(*args, **kwargs)

        _tool_wrapper.__name__ = config.name
        _tool_wrapper.__doc__ = tool.__doc__
        
        if return_to_caller:
            self._pydantic_agent.tool(name=config.name)(_tool_wrapper)
        else:
            self._pydantic_agent.system_prompt(f"Use output tool {config.name} to return final result.")
            self._pydantic_agent.tool(name=config.name)(_tool_wrapper)

        return config

    async def run(self, input_data: Any, message_history: Optional[MessageHistoryBase] = None, context: Any = None) -> AgentResult:
        
        # Convert history if provided
        framework_messages = message_history.to_framework_messages() if message_history else []
        
        # Run Pydantic AI
        result = await self._pydantic_agent.run(
            user_prompt=str(input_data),
            deps=context,
            message_history=framework_messages
        )
        
        # Map back to UniversalMessages
        new_messages = []
        for msg in result.new_messages():
            # Simplistic mapping for now
            new_messages.append(UniversalMessage.create(
                role="assistant", # Simplified
                content=str(result.data),
                metadata={"usage": result.usage().dict()} if result.usage() else {}
            ))
            
        return AgentResult(
            input_data=input_data,
            output=result.data,
            new_messages=new_messages,
            metadata={"usage": result.usage().dict()} if result.usage() else {}
        )
