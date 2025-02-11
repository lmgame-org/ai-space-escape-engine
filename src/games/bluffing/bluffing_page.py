from fastapi import APIRouter, HTTPException, Query, Depends  # Added 'Depends'
from typing import Dict, Optional
import uuid
import json

from src.games.bluffing.bluffing_game import BluffingGame
# from src.games.game_sessions import games  # Commented out; no longer using in-memory game sessions
from src.fschat.api_provider_game import get_api_provider_stream_iter

# Added imports for database usage
from src.database import get_db, GameSession, GameState  # Importing database session and models
from sqlalchemy.orm import Session  # Importing Session for type hinting
from src.fschat.conversation_game import Conversation  # Importing Conversation class
from src.users.user_utilities import update_user_db, ensure_user_exists, extract_difficulty

import os
import json

router = APIRouter()

@router.post("/start")
def bluffing_start(
    ingame_id: str = Query(default="null-id", description="Specify the in game: gameState.aiEscapeRoomID"),
    level: Optional[int] = Query(default=1, ge=1, le=3, description="Specify the level of the game (1 to 3)"),
    user_id: Optional[int] = Query(default=0, description="Specify the user ID (default is 0)"),
    username: Optional[str] = Query(default="anonymous", description="Specify the username"),  # Added 'username' parameter
    db: Session = Depends(get_db)  # Added 'db' parameter for database session
):
    session_id = str(uuid.uuid4())
    difficulty = extract_difficulty(ingame_id)
    game = BluffingGame(difficulty=difficulty, game_level=level, user_id=user_id, username=username)
    # games[session_id] = game  # Commented out; no longer using 'games' dict

    user_statement = game.system_question["bluffing_statement"]
    # Store the user's initial statement and truthfulness
    game.first_user_message = f"Statement: {user_statement}"

    game.user_statement_truth = 'False'  # FIXME: currently we assume all statements are False --> users need to convince AI they are true

    # Update conversation
    game.initialize_game(game.conversation)

    next_llm_query_type = "question"

    game.update_AI_conversation(game.conversation, None)

    ai_message = game.generation_response(
        next_llm_query_type,
        get_api_provider_stream_iter,
        game.conversation,
    )

    ensure_user_exists(user_id=user_id, username=username, db=db)

    # Create a new GameSession in the database
    new_session = GameSession(
        session_id=session_id,
        user_id=user_id,
        username=username,
        game_name="Bluffing",
        state=GameState.PLAYING,
        target_phrase=json.dumps(game.system_question),  # Store the system question
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
        "message": "Bluffing game started.",
        "ai_message": ai_message,
        "session_id": session_id,
        "system_prompt": game.system_prompt,
        "game_secret": game.system_question,
        "instructions": "Please provide your initial statement using the '/provide_statement' endpoint."
    }

@router.post("/assistant")
def bluffing_assistant(session_id:str,
                       db:Session = Depends(get_db)):
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Bluffing").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")
    
    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = BluffingGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id = game_session.user_id,
        username = game_session.username,
        conversation=conversation,
        system_question=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, retrieve any other necessary attributes
    game.system_question = json.loads(game_session.target_phrase)
    game.user_statement_truth = 'False'  # FIXME: retrieve from game session if stored

    parsed_game_history = 'Game History: ' + game.parse_game_history(game_session.history) + '   Based on the game history, please provide two potential responses in the format without anyother explanation:\nAnswer 1: ...\nAnswer 2: ...'
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
# LLM asks question
def bluffing_ask_question(session_id: str, 
                          user_response: Dict[str, str], 
                          db: Session = Depends(get_db)):  # Added 'db' parameter
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Bluffing").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = BluffingGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id = game_session.user_id,
        username = game_session.username,
        conversation=conversation,
        system_question=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, retrieve any other necessary attributes
    game.system_question = json.loads(game_session.target_phrase)
    game.user_statement_truth = 'False'  # FIXME: retrieve from game session if stored

    if game.is_game_over():
        return {
            "message": "Game over.",
            "status": game.game_status
        }

    user_text = user_response.get('user_response')
    if not user_text:
        raise HTTPException(status_code=400, detail="No user response provided.")

    # ------ for the last round, enforce AI to make a guess ------ #
    if game.round + 1 >= game.max_rounds and not game.is_game_over():
        user_text = user_text + "\n\nProvided responses above, please make a judgement on whether the statement is True or False with an analysis."
    # ------ for the last round, enforce AI to make a guess ------ #

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

    # Check if AI made a guess
    end_reason = None
    if game.is_llm_giving_answer(ai_message):
        if game.check_user_win(ai_message, game.user_statement_truth):
            game.set_game_status('PLAYER_WIN')
            end_reason = "LLM_FAILED"
        else:
            game.set_game_status('PLAYER_LOSE')
            end_reason = "LLM_SUCCEEDED"

    # Check for max rounds
    if game.round >= game.max_rounds and not game.is_game_over():
        # LLM fails to make a guess despite of best efforts
        game.set_game_status('PLAYER_WIN')
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
# LLM asks question
def bluffing_regenerate(session_id: str, db: Session = Depends(get_db)):
    # Retrieve the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Bluffing").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")

    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = BluffingGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id = game_session.user_id,
        username = game_session.username,
        conversation=conversation,
        system_question=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )
    # Also, retrieve any other necessary attributes
    game.system_question = json.loads(game_session.target_phrase)
    game.user_statement_truth = 'False'  # FIXME: retrieve from game session if stored

    if game.is_game_over():
        return {
            "message": "Game over.",
            "status": game.game_status
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

    # Update conversation with AI message
    # game.update_AI_conversation(game.conversation, ai_message)

    # Check if AI made a guess
    if game.is_llm_giving_answer(ai_message):
        if game.check_user_win(ai_message, game.user_statement_truth):
            game.set_game_status('PLAYER_WIN')
            user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=1, db=db)
        else:
            game.set_game_status('PLAYER_LOSE')
            user_status = update_user_db(user_id=game_session.user_id, username=game_session.username, addToStars=-1, db=db)

    # Check for max rounds
    if game.round >= game.max_rounds and not game.is_game_over():
        # LLM fails to make a guess despite of best efforts
        game.set_game_status('PLAYER_WIN')
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
def bluffing_hint(session_id: str, db: Session = Depends(get_db)):
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Bluffing").first()
    if not game_session:
        raise HTTPException(status_code=400, detail="Invalid or missing session_id.")
    
    # Reconstruct the conversation with messages from the game session
    conversation = Conversation(
        messages=game_session.history,
        system_message=game_session.system_prompt  # Using stored system_prompt
    )

    # Reconstruct the game state with all necessary attributes
    game = BluffingGame(
        difficulty="dummy",
        game_level=game_session.level,
        user_id = game_session.user_id,
        username = game_session.username,
        conversation=conversation,
        system_question=game_session.target_phrase,
        round=game_session.round,
        game_over=game_session.game_over,
        game_status=game_session.game_status,
        model_name=game_session.model
    )

    print(f"hint game round: {game.round}")
    if game.round == 1:
        system_info = game.system_question
        bluffing_topic = system_info['topic']
        bluffing_statement = system_info['bluffing_statement']

        hint_message = (
            f"Your goal is to make Cypress believe in your statement: {bluffing_statement}\n"
            f"This statement is about: {bluffing_topic.lower()} Your can start by answering the first question.\n"
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
def bluffing_end_game(session_id: str, db: Session = Depends(get_db)):  # Added 'db' parameter
    # Delete the game session from the database
    game_session = db.query(GameSession).filter_by(session_id=session_id, game_name="Bluffing").first()
    if game_session:
        db.delete(game_session)
        db.commit()
    return {"message": "Bluffing game ended."}