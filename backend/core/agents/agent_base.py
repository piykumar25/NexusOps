from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase

@dataclass
class AgentMetadata:
    name: str
    description: str
    retries: int = 3

@dataclass
class ToolConfig:
    tool: Callable
    name: str
    enabled: bool = True
    use_cache: bool = False
    return_to_caller: bool = True

@dataclass
class AgentResult:
    input_data: Any
    output: Any
    new_messages: List[UniversalMessage]
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class AgentBase:
    """Abstract base class contract for all agents."""
    def __init__(self, metadata: AgentMetadata, output_type: Any, deps_type: Any = None):
        self.metadata = metadata
        self.output_type = output_type
        self.deps_type = deps_type
        self.tools: Dict[str, ToolConfig] = {}

    def add_tool(self, tool: Callable, name: Optional[str] = None, enabled: bool = True, use_cache: bool = False, return_to_caller: bool = True) -> ToolConfig:
        tool_name = name or tool.__name__
        config = ToolConfig(tool=tool, name=tool_name, enabled=enabled, use_cache=use_cache, return_to_caller=return_to_caller)
        self.tools[tool_name] = config
        return config

    def enable_tool(self, name: str):
        if name in self.tools:
            self.tools[name].enabled = True

    def disable_tool(self, name: str):
        if name in self.tools:
            self.tools[name].enabled = False

    async def run(self, input_data: Any, message_history: Optional[MessageHistoryBase] = None, context: Any = None) -> AgentResult:
        raise NotImplementedError 
