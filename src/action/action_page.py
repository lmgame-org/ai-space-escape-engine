# src/action/npc_page.py

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Dict, Optional
import uuid
import json
import os

from src.action.action import Action
from src.fschat.api_provider_game import get_api_provider_stream_iter
from src.database import get_db, ActionSession  # Import ActionSession
from sqlalchemy.orm import Session
from src.fschat.conversation_game import Conversation

router = APIRouter()

# Load Action prompts
ACTION_PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'action_prompts.json')
with open(ACTION_PROMPT_FILE, 'r') as f:
    NPC_PROMPTS = json.load(f)

@router.post("/start")
def npc_start(
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),
    db: Session = Depends(get_db)  # Added database dependency
):
    """
    Start a conversation with an NPC by name.
    """
    name = "Human"
    npc_data = NPC_PROMPTS.get(name)
    if not npc_data:
        raise HTTPException(status_code=404, detail="NPC not found")

    session_id = str(uuid.uuid4())
    action = Action(system_prompt=npc_data['prompt'])

    # Start the conversation
    initial_message = f"Hello, {npc_data['name']}!"
    action.update_user_conversation(action.conversation, initial_message)

    npc_response, actions = action.generation_response(
        get_api_provider_stream_iter,
        action.conversation,
    )

    print(npc_response)
    print(actions)

    # Save session to the database
    new_session = ActionSession(
        session_id=session_id,
        username=username,
        model=action.model_name,
        history=action.conversation.messages,
        system_prompt=action.system_prompt
    )
    db.add(new_session)
    db.commit()

    return {
        "message": f"Conversation with {npc_data['name']} started.",
        "npc_response": npc_response,
        "actions": actions,
        "session_id": session_id
    }

# Import BaseModel from pydantic
from pydantic import BaseModel

# Define the request body model
class actionChatRequest(BaseModel):
    session_id: str
    user_input: str

@router.post("/chat")
def npc_chat(
    request_data: actionChatRequest,
    db: Session = Depends(get_db)
):
    """
    Continue the conversation with the NPC.
    """
    session_id = request_data.session_id
    user_text = request_data.user_input

    # Retrieve the session from the database
    npc_session = db.query(ActionSession).filter_by(session_id=session_id).first()
    if not npc_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation
    conversation = Conversation(
        messages=npc_session.history,
        system_message=npc_session.system_prompt
    )

    action = Action(
        model_name=npc_session.model,
        conversation=conversation,
        system_prompt=npc_session.system_prompt
    )

    if not user_text:
        raise HTTPException(status_code=400, detail="No user input provided.")

    # Update conversation with user input
    action.update_user_conversation(action.conversation, user_text)

    # Generate NPC response
    npc_response, actions = action.generation_response(
        get_api_provider_stream_iter,
        action.conversation,
    )

    # Update session history in the database
    npc_session.history = action.conversation.messages
    db.add(npc_session)
    db.commit()

    return {
        "npc_response": npc_response,
        "actions": actions
    }

@router.post("/action/end")
def npc_end(session_id: str, db: Session = Depends(get_db)):
    """
    End the conversation with the NPC.
    """
    # Delete the session from the database
    npc_session = db.query(ActionSession).filter_by(session_id=session_id).first()
    if npc_session:
        db.delete(npc_session)
        db.commit()
        return {"message": "NPC conversation ended."}
    else:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")