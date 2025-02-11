from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from src.database import get_db, GameSession

router = APIRouter()


@router.post("/end")
def update_game_session(
    session_id: str = Query(..., description="Unique identifier for the game session"),
    total_game_time: int = Query(1500, description="Total time spent by the player in the minigame (in seconds, default is 1500 seconds or 25 minutes)", ge=0),
    escape_ai_room_id: Optional[str] = Query(None, description="Unique identifier for the Escape AI Room game"),
    db: Session = Depends(get_db),
):
    game_session = db.query(GameSession).filter(GameSession.session_id == session_id).first()
    if not game_session:
        raise HTTPException(status_code=404, detail="Game session not found")
    
    game_session.total_game_time = total_game_time
    game_session.escape_ai_room_id = escape_ai_room_id

    print("game ending...")
    print(f"game run id: {game_session.escape_ai_room_id}")
    print(f"saving total time: {game_session.total_game_time}")

    db.commit()
    db.refresh(game_session)

    return game_session.to_dict()