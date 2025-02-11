import json
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Enum, JSON, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.ext.mutable import MutableList

import enum
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'users.db')}"  # Database file is 'users.db'
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class GameState(enum.Enum):
    WIN = "win"
    LOSS = "loss"
    PLAYING = "playing"
    FORFEIT = "forfeit"

class GameSession(Base):
    __tablename__ = "game_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), unique=True, index=True)  # UUID is 36 characters
    user_id = Column(Integer, index=True)
    username = Column(String(), index=True)
    game_name = Column(String(), index=True)  # Akinator, Taboo, Bluffing
    state = Column(Enum(GameState), default=GameState.PLAYING)
    target_phrase = Column(String)
    model = Column(String)
    share = Column(Boolean, default=False)
    history = Column(MutableList.as_mutable(JSON), default=[])
    timestamp = Column(DateTime, default=func.now())
    round = Column(Integer, default=0)
    game_over = Column(Boolean, default=False)
    game_status = Column(String)
    level = Column(Integer, default=1)  # Added level field
    system_prompt = Column(String)
    game_stat_change = Column(JSON)  # Added game_stat_change field
    total_game_time = Column(Integer) # Added spent time for a game session
    escape_ai_room_id = Column(String(), index=True) # Added the whole escape ai room game id 

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "game_name": self.game_name,
            "level": self.level,
            "state": self.state.value,
            "target_phrase": self.target_phrase,
            "model": self.model,
            "share": self.share,
            "history": self.history,
            "timestamp": self.timestamp.isoformat(),
            "round": self.round,
            "game_over": self.game_over,
            "game_status": self.game_status,
            "system_prompt": self.system_prompt,
            "game_stat_change": self.game_stat_change,
            "total_game_time": self.total_game_time,
            "escape_ai_room_id": self.escape_ai_room_id
        }

class UserStars(Base):
    __tablename__ = "user_stars"

    roblox_id = Column(Integer, primary_key=True, index=True)  # roblox_id as primary key
    username = Column(String(), index=True)  # Username can change
    stars = Column(Integer, default=0)
    consecutive_wins = Column(Integer, default=0)
    max_consecutive_wins = Column(Integer, default=0)

    def to_dict(self):
        return {
            "roblox_id": self.roblox_id,
            "username": self.username,
            "stars": self.stars,
            "consecutive_wins": self.consecutive_wins,
            "max_consecutive_wins": self.max_consecutive_wins
        }

# Added NPCSession table
class NPCSession(Base):
    __tablename__ = "npc_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), unique=True, index=True)
    username = Column(String(), index=True)
    npc_name = Column(String(), index=True)
    model = Column(String)
    history = Column(MutableList.as_mutable(JSON), default=[])
    system_prompt = Column(String)
    timestamp = Column(DateTime, default=func.now())

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "username": self.username,
            "npc_name": self.npc_name,
            "model": self.model,
            "history": self.history,
            "system_prompt": self.system_prompt,
            "timestamp": self.timestamp.isoformat(),
        }
    
# Added ActionSession table
class ActionSession(Base):
    __tablename__ = "action_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), unique=True, index=True)
    username = Column(String(), index=True)
    model = Column(String)
    history = Column(MutableList.as_mutable(JSON), default=[])
    system_prompt = Column(String)
    timestamp = Column(DateTime, default=func.now())

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "username": self.username,
            "model": self.model,
            "history": self.history,
            "system_prompt": self.system_prompt,
            "timestamp": self.timestamp.isoformat(),
        }


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
# Create the database tables if they don't exist
Base.metadata.create_all(bind=engine)