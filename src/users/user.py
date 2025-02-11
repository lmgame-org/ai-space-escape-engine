# src/users/user.py

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from src.database import get_db, UserStars

router = APIRouter()

@router.post("/user")
def create_user(
    roblox_id: int = Query(..., description="Roblox User ID"),
    username: str = Query(..., description="Username"),
    stars: int = Query(0, description="Number of stars", ge=0),
    db: Session = Depends(get_db)
):
    """
    Create a new user with roblox_id, username, and initial stars.
    """
    user = db.query(UserStars).filter(UserStars.roblox_id == roblox_id).first()
    if user:
        raise HTTPException(status_code=400, detail="User already exists")
    else:
        new_user = UserStars(roblox_id=roblox_id, username=username, stars=stars)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user.to_dict()

@router.get("/user")
def get_user(roblox_id: int = Query(..., description="Roblox User ID"), db: Session = Depends(get_db)):
    """
    Retrieve a user's stars by roblox_id.
    """
    user = db.query(UserStars).filter(UserStars.roblox_id == roblox_id).first()
    if user:
        print('Check Existing User')
        return user.to_dict()
    else:
        print("No User Found")
        raise HTTPException(status_code=404, detail="User not found")

@router.put("/user")
def update_user(
    roblox_id: int = Query(..., description="Roblox User ID"),
    stars: Optional[int] = Query(None, description="Number of stars", ge=0),
    username: Optional[str] = Query(None, description="Username"),
    db: Session = Depends(get_db)
):
    """
    Update a user's stars and/or username by roblox_id.
    """
    user = db.query(UserStars).filter(UserStars.roblox_id == roblox_id).first()
    if user:
        if stars is not None:
            user.stars = stars
        if username is not None:
            user.username = username
        db.commit()
        db.refresh(user)
        return user.to_dict()
    else:
        raise HTTPException(status_code=404, detail="User not found")