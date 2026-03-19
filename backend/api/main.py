from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from backend.core.agents.coordinator import MasterCoordinator
from backend.core.memory.conversation_service import ConversationService
from backend.core.db.database import get_db
import os

app = FastAPI(title="AI DevOps Ops Center API")

class ChatRequest(BaseModel):
    message: str
    session_id: str

@app.post("/api/chat")
async def chat(request: ChatRequest, db=Depends(get_db)):
    # Dependency Injection
    # To run this properly, we need OLLAMA_BASE_URL or OPENAI_API_KEY
    model_name = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    
    coordinator = MasterCoordinator(model_name=model_name, qdrant_url=qdrant_url)
    
    # 1. Load Session
    service = ConversationService(db)
    history = service.load_or_create_session(session_id=request.session_id)
    
    # 2. Run Coordinator
    try:
        result = await coordinator.run(input_data=request.message, message_history=history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # 3. Save Session
    service.append_and_save(session_id=request.session_id, new_messages=result.new_messages)
    
    return result.output
