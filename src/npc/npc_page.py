# src/npc/npc_page.py

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Dict, Optional
import uuid
import json
import os

from src.npc.base_npc import BaseNPC
from src.fschat.api_provider_game import get_api_provider_stream_iter
from src.database import get_db, NPCSession  # Import NPCSession
from sqlalchemy.orm import Session
from src.fschat.conversation_game import Conversation

router = APIRouter()

# Load NPC prompts
NPC_PROMPTS_FILE = os.path.join(os.path.dirname(__file__), 'npc_prompts.json')
with open(NPC_PROMPTS_FILE, 'r') as f:
    NPC_PROMPTS = json.load(f)

@router.post("/npc/start")
def npc_start(
    name: str = Query(..., description="Name of the NPC"),
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),
    db: Session = Depends(get_db)  # Added database dependency
):
    """
    Start a conversation with an NPC by name.
    """
    npc_data = NPC_PROMPTS.get(name)
    if not npc_data:
        raise HTTPException(status_code=404, detail="NPC not found")

    session_id = str(uuid.uuid4())
    npc = BaseNPC(system_prompt=npc_data['prompt'])

    # Start the conversation
    initial_message = f"Hello, {npc_data['name']}!"
    npc.update_user_conversation(npc.conversation, initial_message)

    npc_response, animations = npc.generation_response(
        get_api_provider_stream_iter,
        npc.conversation,
    )

    print(npc_response)
    print(animations)

    # Save session to the database
    new_session = NPCSession(
        session_id=session_id,
        username=username,
        npc_name=name,
        model=npc.model_name,
        history=npc.conversation.messages,
        system_prompt=npc.system_prompt
    )
    db.add(new_session)
    db.commit()

    return {
        "message": f"Conversation with {npc_data['name']} started.",
        "npc_response": npc_response,
        "animations": animations,
        "session_id": session_id
    }

# Import BaseModel from pydantic
from pydantic import BaseModel

# Define the request body model
class NPCChatRequest(BaseModel):
    session_id: str
    user_input: str

@router.post("/npc/chat")
def npc_chat(
    request_data: NPCChatRequest,
    db: Session = Depends(get_db)
):
    """
    Continue the conversation with the NPC.
    """
    session_id = request_data.session_id
    user_text = request_data.user_input

    # Retrieve the session from the database
    npc_session = db.query(NPCSession).filter_by(session_id=session_id).first()
    if not npc_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation
    conversation = Conversation(
        messages=npc_session.history,
        system_message=npc_session.system_prompt
    )

    npc = BaseNPC(
        model_name=npc_session.model,
        conversation=conversation,
        system_prompt=npc_session.system_prompt
    )

    if not user_text:
        raise HTTPException(status_code=400, detail="No user input provided.")

    # Update conversation with user input
    npc.update_user_conversation(npc.conversation, user_text)

    # Generate NPC response
    npc_response, animations = npc.generation_response(
        get_api_provider_stream_iter,
        npc.conversation,
    )

    # Update session history in the database
    npc_session.history = npc.conversation.messages
    db.add(npc_session)
    db.commit()

    return {
        "npc_response": npc_response,
        "animations": animations
    }

@router.post("/npc/end")
def npc_end(session_id: str, db: Session = Depends(get_db)):
    """
    End the conversation with the NPC.
    """
    # Delete the session from the database
    npc_session = db.query(NPCSession).filter_by(session_id=session_id).first()
    if npc_session:
        db.delete(npc_session)
        db.commit()
        return {"message": "NPC conversation ended."}
    else:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")