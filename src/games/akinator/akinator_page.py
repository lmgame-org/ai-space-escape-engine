from fastapi import APIRouter, HTTPException, Query  # Original imports
from fastapi import APIRouter, HTTPException, Query, Depends  # Added 'Depends' for dependency injection
from typing import Dict, Optional
import uuid

from src.games.akinator.akinator_game import AkinatorGame
# from src.games.game_sessions import games  # Commented out; no longer using in-memory game sessions
from src.fschat.api_provider_game import get_api_provider_stream_iter

# Added imports for database usage
from src.database import get_db, GameSession, GameState, UserStars # Importing database session and models
from sqlalchemy.orm import Session  # Importing Session for type hinting
from src.fschat.conversation_game import Conversation  # Importing Conversation class
from src.users.user_utilities import update_user_db, ensure_user_exists, extract_difficulty

import os
import json
import re

router = APIRouter()


@router.post("/start")
def akinator_start(
    use_secret_word: str = Query(default="false", description="Whether to use (user-)provided secret word"),
    ingame_id: str = Query(default="null-id", description="Specify the in game: gameState.aiEscapeRoomID"),
    secret_word: Optional[str] = Query(default="apple", description="Specify the username"),
    level: Optional[int] = Query(default=1, ge=1, le=3, description="Specify the level of the game (1 to 3)"),
    user_id: Optional[int] = Query(default=0, description="Specify the user ID (default is 0)"),
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),  # Added 'username' parameter
    db: Session = Depends(get_db)  # Added 'db' parameter for database session
):
    """
    Start a new game with an optional level parameter.
    """

    def convert_to_bool(s: str) -> bool:
        s_lower = s.strip().lower()
        if s_lower == "true":
            return True
        elif s_lower == "false":
            return False
        else:
            raise ValueError(f"Invalid boolean string: {s!r}")
    
    session_id = str(uuid.uuid4())
    use_secret_word = convert_to_bool(use_secret_word)

    difficulty = extract_difficulty(ingame_id)

    # Apply filtering to user-provided secret word
    # 1) make sure it's a single-word
    def extract_first_word(input_string):
        # Use regex to find the first sequence of alphanumeric characters
        match = re.search(r'\b\w+\b', input_string)
        return match.group(0) if match else ''

    # TODO (lanxiang): add better filtering mechanism
    secret_word = extract_first_word(secret_word)

    if use_secret_word:
        game = AkinatorGame(level=level, difficulty=difficulty, user_id=user_id, username=username, game_secret=secret_word)
        game.user_provided_secret = True
    else:
        game = AkinatorGame(level=level, difficulty=difficulty, user_id=user_id, username=username)
    # games[session_id] = game  # Commented out; no longer using "games" dict

    game.initialize_game(game.conversation)

    next_llm_query_type = "question"
    game.update_AI_conversation(game.conversation, None)

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    # Update conversation with AI message
    ensure_user_exists(user_id=user_id, username=username, db=db)

    # Create a new GameSession in the database
    new_session = GameSession(
        session_id=session_id,
        user_id=user_id,
        username=username,
        game_name="Akinator",
        state=GameState.PLAYING,
        target_phrase=game.game_secret,
        model=game.model_name,
        history=game.conversation.messages,
        round=game.round,
        game_over=game.game_over,
        game_status=game.game_status,
        level=level,
        system_prompt=game.system_prompt  # Storing system_prompt
    )  # Added code to create a new GameSession
    db.add(new_session)  # Add the session to the database
    db.commit()  # Commit the transaction

    return {
        "message": "Akinator game started at level {}".format(level),
        "ai_message": ai_message,
        "session_id": session_id,
        "system_prompt": game.system_prompt,
        "game_secret": game.game_secret  # For testing purposes; remove in production
    }

@router.post("/ask_question")
def akinator_ask_question(session_id: str, 
                          user_response: Dict[str, str],  
                          db: Session = Depends(get_db)):  # Added 'db' parameter

    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Akinator").first()  # Fetch game session
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )  # Reconstructed conversation with previous messages

    game = AkinatorGame(
        user_id = game_session.user_id,
        username = game_session.username,
        level=game_session.level,
        difficulty="dummy",
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,  # Changed 'current_round' to 'round'
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )

    if game.reach_max_round():  # Max rounds reached
        game.set_game_status('PLAYER_LOSE')
        # Update UserState in the database
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=-1, db=db)

        # Update the game session in the database
        game_session.game_over = game.game_over
        game_session.game_status = game.game_status
        db.add(game_session)
        db.commit()

        return {
            "message": "Game over.",
            "game_over": game.is_game_over(),
            "game_status": game.game_status
        }

    user_text = user_response.get('user_response')
    if not user_text:
        raise HTTPException(status_code=400, detail="No user response provided.")
    if user_text.lower() not in (answer.lower() for answer in game.allowed_answers):
        raise HTTPException(status_code=400, detail="Please provide a valid answer. Allowed answers are required.")

    # Update conversation with user response
    game.update_user_conversation(game.conversation, user_text)

    next_llm_query_type = "question"

    game.update_AI_conversation(game.conversation, None)

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    # Update conversation with AI message
    # game.update_AI_conversation(game.conversation, ai_message)

    # Check if game is over:
    if game.check_akinator_valid_guess(ai_message):  # LLM guessed the word
        if game.guessed_word_correctly(ai_message):
            game.set_game_status('PLAYER_WIN')
            # Update User State in the database
            user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=1, db=db)

    # Update the game session in the database
    game_session.history = game.conversation.messages

    game_session.round = game.round
    print("INSERT ROUND: " + str(game_session.round))
    game_session.game_over = game.game_over
    game_session.game_status = game.game_status
    db.add(game_session)  # Add the updated session to the database
    db.commit()  # Commit the transaction
    
    return {
        "ai_message": ai_message,
        "round": game.round,
        "game_over": game.is_game_over(),
        "game_status": game.game_status
    }

@router.post("/regenerate")
def akinator_regenerate(session_id: str, db: Session = Depends(get_db)):
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Akinator").first()  # Fetch game session
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )  # Reconstructed conversation with previous messages

    game = AkinatorGame(
        user_id = game_session.user_id,
        username = game_session.username,
        level=game_session.level,
        difficulty="dummy",
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,  # Changed 'current_round' to 'round'
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )

    if game.reach_max_round():  # Max rounds reached
        game.set_game_status('PLAYER_LOSE')
        # Update UserState in the database
        user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=-1, db=db)

        # Update the game session in the database
        game_session.game_over = game.game_over
        game_session.game_status = game.game_status
        db.add(game_session)
        db.commit()

        return {
            "message": "Game over.",
            "game_over": game.is_game_over(),
            "game_status": game.game_status
        }

    # prepare for regeneration
    game.round -= 1
    game.conversation.update_last_message(None)

    next_llm_query_type = "question"

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    # Check if game is over:
    if game.check_akinator_valid_guess(ai_message):  # LLM guessed the word
        if game.guessed_word_correctly(ai_message):
            game.set_game_status('PLAYER_WIN')
            # Update User State in the database
            user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=1, db=db)

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
def akinator_hint(use_secret_word: bool, session_id: str, db: Session = Depends(get_db)):
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Akinator").first()  # Fetch game session
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )  # Reconstructed conversation with previous messages

    game = AkinatorGame(
        user_id = game_session.user_id,
        username = game_session.username,
        level=game_session.level,
        difficulty="dummy",
        conversation=conversation,
        game_secret=game_session.target_phrase,
        round=game_session.round,  # Changed 'current_round' to 'round'
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )

    if use_secret_word:
        if game.round == 1:
            secret_word = game_session.target_phrase

            hint_message = (
                f"Your goal is to make Cypress correctly guess the word: {secret_word}.\n"
                f"Your can start by answering the first question.\n"
            )
        else:
            parsed_game_history = game.hint_prompt + "\n\nGame History:\n\n" + game.parse_game_history(game_session.history)
            new_message = [["user", parsed_game_history]]

            new_conversation = Conversation(
                messages=new_message,
            )

            hint_message = game.generation_assistant_response(
                "hint",
                get_api_provider_stream_iter,
                new_conversation,
            )
    else:
        game_secret_file = os.path.join(os.path.dirname(__file__), 'akinator.json')
        with open(game_secret_file, 'r') as f:
            game_secrets = json.load(f)
        hint_message = game_secrets[game.game_secret]
    
    return {
        "session_id": session_id,
        "hint_message": hint_message
    }

@router.post("/end_game")
def akinator_end_game(session_id: str, db: Session = Depends(get_db)):  # Added 'db' parameter
    # Delete the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Akinator").first()
    if game_session:
        db.delete(game_session)
        db.commit()
    return {"message": "Akinator game ended."}