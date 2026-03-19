from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union
import datetime

@dataclass
class UniversalMessage:
    """Universal message format used across all agents in the system."""
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, List[Dict[str, Any]]] 
    timestamp: str 
    metadata: Dict[str, Any] = field(default_factory=dict)
    turn_idx: Optional[int] = None

    @classmethod
    def create(cls, role: Literal["system", "user", "assistant", "tool"], content: Union[str, List[Dict[str, Any]]], turn_idx: Optional[int] = None, metadata: Dict[str, Any] = None):
        return cls(
            role=role,
            content=content,
            timestamp=datetime.datetime.utcnow().isoformat(),
            metadata=metadata or {},
            turn_idx=turn_idx
        )

class MessageHistoryBase:
    """Base class for managing conversation history."""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[UniversalMessage] = []
        self.conversational_messages: List[UniversalMessage] = []
        self.current_turn_idx = 0

    def append(self, message: UniversalMessage):
        self.messages.append(message)
        if message.role in ("user", "assistant", "system"):
            self.conversational_messages.append(message)

    def append_agent_result(self, result: Any):
        """Extracts messages from AgentResult and appends them."""
        for msg in result.new_messages:
            msg.turn_idx = self.current_turn_idx
            self.append(msg)
        self.current_turn_idx += 1
        
    def to_framework_messages(self) -> List[Any]:
        raise NotImplementedError

    def from_framework_messages(self, messages: List[Any]):
        raise NotImplementedError
