from sqlalchemy.orm import Session
from backend.core.db.models import ConversationSession
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase
import json
from uuid import uuid4

class PydanticMessageHistory(MessageHistoryBase):
    """Bridge for full message history to Pydantic AI framework."""
    def to_framework_messages(self):
        # In a real app, map UniversalMessage to pydantic_ai message types
        return [msg.content for msg in self.messages]

class ConversationService:
    def __init__(self, db_session: Session):
        self.db = db_session

    def load_or_create_session(self, session_id: str = None, user_id: str = "system", agent_id: str = "default") -> PydanticMessageHistory:
        sid = session_id or str(uuid4())
        record = self.db.query(ConversationSession).filter(ConversationSession.session_id == sid).first()
        
        history = PydanticMessageHistory(session_id=sid)
        
        if record:
            # Rehydrate 
            for msg_dict in record.full_history:
                history.append(UniversalMessage(**msg_dict))
        else:
            # Create new
            new_session = ConversationSession(session_id=sid, user_id=user_id, agent_id=agent_id)
            self.db.add(new_session)
            self.db.commit()
            
        return history

    def append_and_save(self, session_id: str, new_messages: list[UniversalMessage]):
        record = self.db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
        if record:
            current_history = list(record.full_history)
            for msg in new_messages:
                current_history.append(msg.__dict__)
            record.full_history = current_history
            self.db.commit()
