from sqlalchemy import Column, Integer, String, DateTime, JSON
from backend.core.db.database import Base
from datetime import datetime

class ConversationSession(Base):
    __tablename__ = "taara_conversation_details"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    agent_id = Column(String, nullable=False)
    full_history = Column(JSON, default=list)
    conversational_history = Column(JSON, default=list)
    total_conversational_messages = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
