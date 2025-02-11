from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Dict, Optional
import uuid

from src.games.story_scenario.story_scenario import StoryScenarioGame, load_prompts
from src.fschat.api_provider_game import get_api_provider_stream_iter

from src.database import get_db, GameSession, GameState, UserStars # Importing database session and models
from sqlalchemy.orm import Session  # Importing Session for type hinting
from src.fschat.conversation_game import Conversation  # Importing Conversation class
from src.users.user_utilities import update_user_db, ensure_user_exists

import os
import json

import string

from pydantic import BaseModel

class ScenarioRequest(BaseModel):
    session_id: str
    user_input: str
    choice_index: int

def index_to_alphabet(index: int) -> str:
    """Convert a 0-based index to a corresponding uppercase alphabet letter."""
    return string.ascii_uppercase[index] if 0 <= index < 26 else f"Option {index+1}"

# Import BaseModel from pydantic
from pydantic import BaseModel

router = APIRouter()

@router.post("/start")
def storyscenario_start(
    current_room: Optional[str] = Query(default="random room", description="Specify the current room"),
    user_id: Optional[int] = Query(default=0, description="Specify the user ID (default is 0)"),
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),  # Added 'username' parameter
    db: Session = Depends(get_db)  # Added 'db' parameter for database session 
):
    session_id = str(uuid.uuid4())

    print(f"current room: {current_room}")
    game = StoryScenarioGame(user_id=user_id, current_room=current_room, username=username)

    print("scenario game object sucessfully created.")

    game.initialize_game(game.conversation)
    print("game initialization sucessful.")
    # game.update_user_conversation(game.conversation, game.first_user_message)

    next_llm_query_type = "answer"
    game.update_AI_conversation(game.conversation, None)
    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    ensure_user_exists(user_id=user_id, username=username, db=db)

    print("========== game history ==========")
    print(game.conversation.messages)
    
    new_session = GameSession(
        session_id=session_id,
        user_id=user_id,
        username=username,
        game_name="StoryScenario",
        state=GameState.PLAYING,
        target_phrase=None,
        model=game.model_name,
        history=game.conversation.messages, # remove empty system prompt
        round=game.round,
        game_over=game.game_over,
        game_status=game.game_status,
        game_stat_change=game.stat_change_dict,
        level=1,
        system_prompt=game.system_prompt  # Storing system_prompt
    )  # Added code to create a new GameSession
    db.add(new_session)  # Add the session to the database
    db.commit()  # Commit the transaction

    print("ai message:")
    print(ai_message)

    parsed_results = game.parse_scenario_choices(ai_message)
    scenario_story = parsed_results["Scenario"]
    choice_a = parsed_results["Choice A"]
    choice_b = parsed_results["Choice B"]

    return {
        "message": "StoryScenario game started.",
        "ai_message": scenario_story,
        "session_id": session_id,
        "conversation": game.conversation.messages,
        "options": {"firstOption": choice_a, "secondOption": choice_b},  # added options
        "stat_changes": game.stat_change_dict  # added stat_changes
    }

@router.post("/conclude")
def storyscenario_conclude(
    data: ScenarioRequest,
    db: Session = Depends(get_db)
):  
    session_id = data.session_id
    choice_index = data.choice_index
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="StoryScenario").first()  # Fetch game session
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    print("========== retrieved game history ==========")
    print(game_session.history)

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
    )  # Reconstructed conversation with previous messages

    game = StoryScenarioGame(
        user_id=game_session.user_id,
        username=game_session.username,
        conversation=conversation,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model,
        stat_change_dict=game_session.game_stat_change
    )

    print("========== reinitialized game history ==========")
    print(game.conversation.messages)

    _, prompt_for_outcome = load_prompts()

    option_indx = choice_index
    user_choice = "Choice " + index_to_alphabet(option_indx)

    game_status = game.stat_change_dict[user_choice]
    change_description = game_status['type'] + ": " + str(game_status['value']) + f" (out of {game_status['max']})"
    game.update_user_conversation(game.conversation, prompt_for_outcome.format(user_choice=user_choice, outcome=change_description))

    next_llm_query_type = "answer"
    game.update_AI_conversation(game.conversation, None)
    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    game.game_over = True
    game.game_status = "TERMINATED"

    # update game session state
    game_session.history = game.conversation.messages
    game_session.round = game.round
    game_session.game_over = game.game_over
    game_session.game_status = game.game_status
    game_session.target_phrase = user_choice

    db.add(game_session)  # Add the updated session to the database
    db.commit()  # Commit the transaction

    return {
        "message": "StoryScenario game concluded.",
        "ai_message": ai_message,
        "session_id": session_id,
        "conversation": game.conversation.messages,
        "stat_changes": game.stat_change_dict[user_choice],
        "game_over": game.game_over,
        "game_status": game.game_status
    }