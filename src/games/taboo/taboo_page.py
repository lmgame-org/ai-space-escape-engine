from fastapi import APIRouter, HTTPException, Query, Depends  # Added 'Depends'
from typing import Dict, Optional
import uuid

from src.games.taboo.taboo_game import TabooGame
# from src.games.game_sessions import games  # Commented out; no longer using in-memory game sessions
from src.fschat.api_provider_game import get_api_provider_stream_iter

# Added imports for database usage
from src.database import get_db, GameSession, GameState
from sqlalchemy.orm import Session
from src.fschat.conversation_game import Conversation
from src.users.user_utilities import update_user_db, ensure_user_exists, extract_difficulty

import os
import json

router = APIRouter()

@router.post("/start")
def taboo_start(
    ingame_id: str = Query(default="null-id", description="Specify the in game: gameState.aiEscapeRoomID"),
    level: Optional[int] = Query(default=1, ge=1, le=3, description="Specify the level of the game (1 to 3)"),
    user_id: Optional[int] = Query(default=0, description="Specify the user ID (default is 0)"),
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),  # Added 'username' parameter
    db: Session = Depends(get_db)  # Added 'db' parameter for database session
):
    session_id = str(uuid.uuid4())
    difficulty = extract_difficulty(ingame_id)
    game = TabooGame(difficulty=difficulty, game_level=level)
    # games[session_id] = game  # Commented out; no longer using 'games' dict

    ensure_user_exists(user_id=user_id, username=username, db=db)

    # Create a new GameSession in the database
    new_session = GameSession(
        session_id=session_id,
        user_id=user_id,
        username=username,
        game_name="Taboo",
        state=GameState.PLAYING,
        target_phrase=game.game_secret,
        model=game.model_name,
        history=game.conversation.messages,
        round=game.round,
        game_over=game.game_over,
        game_status=game.game_status,
        level=level,
        system_prompt=game.system_prompt
    )  # Added code to create a new GameSession
    db.add(new_session)  # Add the session to the database
    db.commit()  # Commit the transaction

    return {
        "message": "Taboo game started.",
        "session_id": session_id,
        "system_prompt": game.system_prompt,
        "game_secret": game.game_secret,  # For testing purposes; remove in production
        "game_hint": game.game_hint
    }

@router.post("/assistant")
def taboo_assistant(session_id:str,
                       db:Session = Depends(get_db)):
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Taboo").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")
    
    # Initialize a game to call assistant system prompt
    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = TabooGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id=game_session.user_id,
        username=game_session.username,
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, set game_secret
    game.game_secret = game_session.target_phrase

    parsed_game_history = 'Based on the game history, please provide two potential responses in the format without anyother explanation:\nQuestion 1: ...\nQuestion 2: ...\n\n' + 'Game History: ' + game.parse_game_history(game_session.history)
    assistant_system_prompt = game.choose_assistant_prompt()
    new_message = [["user", parsed_game_history]]

    new_conversation = Conversation(
        messages=new_message,
        system_message=assistant_system_prompt
    )

    ai_message = game.generation_assistant_response(
        "assistant",
        get_api_provider_stream_iter,
        new_conversation,
    )

    possible_answers = game.extract_answer(ai_message)

    return {
        "session_id": session_id,
        "first_response": possible_answers[0],
        "second_response": possible_answers[1]
    }

@router.post("/ask_question")
# LLM answers
def taboo_ask_question(session_id: str, 
                       user_response: Dict[str, str],
                       db: Session = Depends(get_db)):  # Added 'db' parameter
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Taboo").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = TabooGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id=game_session.user_id,
        username=game_session.username,
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, set game_secret
    game.game_secret = game_session.target_phrase

    if game.is_game_over():
        return {
            "message": "Game over.",
            "status": game.game_status
        }

    user_text = user_response.get('user_response')
    if not user_text:
        raise HTTPException(status_code=400, detail="No user response provided.")

    # Update conversation with user response
    if game.round == 0 and "o1" in game_session.model:
        user_text = game.system_prompt + "\n\nFirst user question:\n" + user_text
    game.update_user_conversation(game.conversation, user_text)

    next_llm_query_type = "answer"

    game.update_AI_conversation(game.conversation, None)

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    # First check if the model has attempted a prediction --> game terminates
    end_reason = None
    predict_flag, ai_guess = game.is_llm_giving_answer(ai_message)
    if predict_flag:
        print("LLM is making a prediction!")
        if game.check_user_win(ai_guess):
            print("the prediction is wrong.")
            game.set_game_status('PLAYER_WIN')
            end_reason = "LLM_WRONG_PREDICTION"
        else:
            print("the prediction is correct.")
            game.set_game_status('PLAYER_LOSE')
            end_reason = "LLM_CORRECT_PREDICTION"
    # Taboo-specific game logic: check if the word has been unintentionally generated
    elif game.check_word_uttered(ai_message):
        game.set_game_status('PLAYER_WIN')
        end_reason = "LLM_FAILED"
    elif game.round >= game.max_rounds:
        game.set_game_status('PLAYER_LOSE')
        end_reason = "MAX_ROUND_REACHED"

    if game.game_status == 'PLAYER_WIN':
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=1, db=db)
    elif game.game_status == 'PLAYER_LOSE':
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=-1, db=db)

    # Update the game session in the database
    game_session.history = game.conversation.messages
    game_session.round = game.round
    game_session.game_over = game.game_over
    game_session.game_status = game.game_status
    db.add(game_session)  # Add the updated session to the database
    db.commit()  # Commit the transaction

    return {
        "ai_message": ai_message,
        "round": game.round,
        "game_over": game.is_game_over(),
        "game_status": game.game_status,
        "end_reason": end_reason,
    }

@router.post("/regenerate")
# LLM answers
def taboo_regenerate(session_id: str, db: Session = Depends(get_db)):  # Added 'db' parameter
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Taboo").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = TabooGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id=game_session.user_id,
        username=game_session.username,
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, set game_secret
    game.game_secret = game_session.target_phrase

    if game.is_game_over():
        return {
            "message": "Game over.",
            "status": game.game_status
        }
    
    # prepare for regeneration
    game.round -= 1
    game.conversation.update_last_message(None)

    next_llm_query_type = "answer"

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    # Taboo-specific game logic
    if game.check_word_uttered(ai_message):
        game.game_over = True
        game.game_status = 'PLAYER_WIN'
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=1, db=db)

    elif game.round >= game.max_rounds:
        game.game_over = True
        game.game_status = 'PLAYER_LOSE'
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=-1, db=db)

    # Update the game session in the database
    game_session.history = game.conversation.messages
    game_session.round = game.round
    game_session.game_over = game.game_over
    game_session.game_status = game.game_status
    db.add(game_session)  # Add the updated session to the database
    db.commit()  # Commit the transaction

    return {
        "ai_message": ai_message,
        "game_over": game.is_game_over(),
        "game_status": game.game_status
    }

@router.post("/hint")
def taboo_hint(session_id: str, db: Session = Depends(get_db)):
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Taboo").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")
    
    # Initialize a game to call assistant system prompt
    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )
    
    # Reconstruct the game state with all necessary attributes
    game = TabooGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id=game_session.user_id,
        username=game_session.username,
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )

    print(f"hint game round: {game.round}")
    if game.round == 0:
        game_secret_file = os.path.join(os.path.dirname(__file__), 'taboo.json')
        with open(game_secret_file, 'r') as f:
            game_secrets = json.load(f)
        
        game_level = game.game_level
        level_key = f"level_{game_level}"
        
        level_to_category_map = {
            "level_1": "animals",
            "level_2": "city-country",
            "level_3": "food"
        } # FIXME (lanxiang): set and read this from taboo_game

        game_secret_category = level_to_category_map[level_key]
        level_specific_game_secrets = game_secrets[game_secret_category]
    
        game_secret = game.game_secret
        game_secret_description = level_specific_game_secrets[game_secret]
        hint_message = (
            f"Your goal is to unlock the door by making Cypress say the password: {game_secret}.\n"
            f"Remember, Cypress doesn’t know the password directly but will respond to your questions.\n"
            f"Target word description: {game_secret_description}\n"
        )
    else:
        parsed_game_history = game.prepare_hint_prompt(game_session.history)
        new_message = [["user", parsed_game_history]]

        new_conversation = Conversation(
            messages=new_message,
        )

        hint_message = game.generation_assistant_response(
            "hint",
            get_api_provider_stream_iter,
            new_conversation,
        )
    return {
        "session_id": session_id,
        "hint_message": hint_message
    }

@router.post("/end_game")
def taboo_end_game(session_id: str, db: Session = Depends(get_db)):  # Added 'db' parameter
    # Delete the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Taboo").first()
    if game_session:
        db.delete(game_session)
        db.commit()
    return {"message": "Taboo game ended."}