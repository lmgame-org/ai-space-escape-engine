from src.database import get_db, UserStars
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends 

def extract_difficulty(ingame_id: str) -> str:
        """Extracts the substring after the last hyphen in the given string."""
        return ingame_id.split("-")[-1]

def ensure_user_exists(user_id: int, username: str, db: Session = Depends(get_db)):
    user = db.query(UserStars).filter(UserStars.roblox_id == user_id).first()

    if not user:
        user = UserStars(
            roblox_id=user_id,
            username=username,
            stars=0,
            consecutive_wins=0
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.username = username
        db.commit()
        db.refresh(user)

    return user.to_dict()


def update_user_db(user_id: int, username: str, addToStars: int, db: Session=Depends(get_db)):
    user = db.query(UserStars).filter(UserStars.roblox_id == user_id).first()
    
    if user:
        user.username = username
        if addToStars > 0:  # Winning case
            user.consecutive_wins += 1
            if user.consecutive_wins > 3:
                user.stars = max(0, user.stars + addToStars + 1)  
            else:
                user.stars = max(0, user.stars + addToStars)
        else:  # Losing case
            user.stars = max(0, user.stars + addToStars)
            user.consecutive_wins = 0 
        # update max consecutive wins
        user.max_consecutive_wins = max(user.consecutive_wins, user.max_consecutive_wins)
    else:
        # Create new user entry
        stars = max(0, addToStars)
        consecutive_wins = 1 if addToStars > 0 else 0  # Set consecutive_wins to 1 only if the user wins
        user = UserStars(roblox_id=user_id, username=username, stars=stars, consecutive_wins=consecutive_wins, max_consecutive_wins = consecutive_wins)
        db.add(user)
    db.commit()
    db.refresh(user) 
    
    return user.to_dict()