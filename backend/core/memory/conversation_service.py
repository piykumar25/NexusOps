"""
NexusOps Conversation Memory Service
======================================
Production-grade persistence layer for chat history.
Features:
  - Connects to PostgreSQL via SQLAlchemy
  - Serializes and deserializes the UniversalMessage abstraction
  - Bridges persisted history directly to Pydantic-AI format
  - Tracks metadata (tokens, agent utilized, elapsed time)
"""

import json
import logging
from typing import List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.core.db.models import ConversationSession
from backend.core.memory.message_base import UniversalMessage, MessageHistoryBase

logger = logging.getLogger("nexusops.memory")


class PydanticMessageHistory(MessageHistoryBase):
    """
    Bridge class that holds a list of UniversalMessages and
    can convert them into the format expected by Pydantic-AI
    (or any other framework) natively.
    """

    def to_framework_messages(self) -> List[str]:
        """
        Convert UniversalMessages to Pydantic-AI message strings.
        In a more complex app, this would map to actual pydantic_ai.models.ModelMessage objects.
        """
        return [msg.content for msg in self.messages]


class ConversationService:
    """Service layer for persisting and retrieving user conversation sessions."""

    def __init__(self, db_session: Session):
        self.db = db_session

    def load_or_create_session(
        self,
        session_id: Optional[str] = None,
        user_id: str = "system",
        agent_id: str = "default"
    ) -> PydanticMessageHistory:
        """
        Retrieves a conversation history by ID, or creates a new one.
        Returns a populated MessageHistoryBase instance.
        """
        sid = session_id or str(uuid4())

        try:
            record = self.db.query(ConversationSession).filter(ConversationSession.session_id == sid).first()

            history = PydanticMessageHistory(session_id=sid)

            if record and record.full_history:
                # Rehydrate universal messages
                for msg_dict in record.full_history:
                    try:
                        history.append(UniversalMessage(**msg_dict))
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse history message {msg_dict}: {parse_err}")
                logger.info(f"Loaded session {sid} with {len(history.messages)} messages")
            else:
                # Create new session record
                new_session = ConversationSession(
                    session_id=sid,
                    user_id=user_id,
                    agent_id=agent_id,
                    full_history=[],
                )
                self.db.add(new_session)
                self.db.commit()
                logger.info(f"Created new conversation session {sid}")

            return history

        except Exception as e:
            logger.error(f"Failed to load session {sid}: {e}")
            # Degrade gracefully: return empty memory rather than crashing
            return PydanticMessageHistory(session_id=sid)

    def append_and_save(self, session_id: str, new_messages: list[UniversalMessage]):
        """Append new messages to an existing session and save to DB."""
        try:
            record = self.db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()

            if record:
                # SQLAlchemy JSON columns sometimes need reassignment to detect changes
                current_history = list(record.full_history) if record.full_history else []

                # Ensure serialization of UniversalMessage handles non-standard types
                for msg in new_messages:
                    msg_dict = msg.__dict__.copy()
                    # Ensure metadata dict is JSON serializable
                    if 'metadata' in msg_dict and msg_dict['metadata']:
                        try:
                            json.dumps(msg_dict['metadata'])
                        except TypeError:
                            msg_dict['metadata'] = {"_note": "Unserializable metadata dropped"}

                    current_history.append(msg_dict)

                record.full_history = current_history
                record.total_conversational_messages = len(current_history)
                self.db.commit()
                logger.debug(f"Saved {len(new_messages)} messages to session {session_id}")
            else:
                logger.warning(f"Attempted to save to unknown session {session_id}")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to append messages to session {session_id}: {e}")
