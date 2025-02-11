import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))  # Add the project root to the path
# sys.path.append('/home/ubuntu/game_arena_engine')

from fastapi import FastAPI
from src.games.akinator.akinator_page import router as akinator_router
from src.games.taboo.taboo_page import router as taboo_router
from src.games.bluffing.bluffing_page import router as bluffing_router
from src.games.story_scenario.story_scenario_page import router as story_scenario_router
from src.npc.npc_page import router as npc_router  # Include the NPC router
from src.users.user import router as user_router
from src.action.action_page import router as action_router
from src.games.base_page import router as base_router

app = FastAPI(title="Game Arena", debug=True)

app.include_router(akinator_router, prefix="/akinator")
app.include_router(taboo_router, prefix="/taboo")
app.include_router(bluffing_router, prefix="/bluffing")
app.include_router(npc_router, prefix="/npc")
app.include_router(action_router, prefix="/action")
app.include_router(story_scenario_router, prefix="/scenario")
app.include_router(npc_router, prefix="")  # No prefix, or you can set '/npc'
app.include_router(user_router, prefix="")
app.include_router(base_router, prefix="")

@app.get("/")
def main():
    return {"message": "Welcome to the Game Arena!"}