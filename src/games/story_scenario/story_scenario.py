from src.fschat.conversation_game import Conversation
from src.games.base_game import BaseGame
from typing import Optional, Any, Dict
from pathlib import Path

import json, random

import re

# prompt_for_scenario, prompt_for_outcome
STORY_SCENARIO_PROMPTS_PATH = Path(__file__).parent / "story_scenario_prompts.json"

def load_prompts(prompt_file_path=STORY_SCENARIO_PROMPTS_PATH):
    with open(prompt_file_path, 'r') as f:
        prompts = json.load(f)
        prompt_for_scenario = prompts["prompt_for_scenario"]
        prompt_for_outcome = prompts["prompt_for_outcome"]
        return prompt_for_scenario, prompt_for_outcome

class StoryScenarioGame(BaseGame):
    def __init__(
        self,
        current_room: Optional[str] = "random room",
        user_id: Optional[int] = 0,
        username: Optional[str] = "anonymous",
        conversation: Optional[Conversation] = None,  # Added 'conversation' parameter
        round: int = 0,  # Changed 'current_round' to 'round' to match BaseGame
        game_over: bool = False,  # Added 'game_over' parameter
        game_status: Optional[str] = None,  # Added 'game_status' parameter
        model_name: Optional[str] = "gpt-4o-2024-11-20",  # Added 'model_name' parameter
        stat_change_dict: Optional[Dict[str, str]] = None,
        # scenario_model_name: Optional[str] =   # Added 'scenario_model_name' parameter
    ) -> None:
        conversation = Conversation() if conversation is None else conversation

        # Pass parameters to BaseGame
        super().__init__(
            max_rounds=2,
            round=round,
            model_name=model_name,
            conversation=conversation,
            user_id=user_id,
            username=username
        )

        # Removed self.current_round; using self.round from BaseGame

        # Set attributes from parameters or defaults
        self.game_over = game_over  # Set game_over
        self.game_status = game_status  # Set game_status

        self.current_room = current_room
        # self.model_name is set in BaseGame
        
        if not stat_change_dict:
            prompt_for_scenario, _ = load_prompts()
            stat_change_choice_A, stat_change_choice_A_num, stat_change_choice_A_cap = self.get_stat_change()
            stat_change_choice_B, stat_change_choice_B_num, stat_change_choice_B_cap = self.get_stat_change()
            
            # randomly choose one to become negative
            if random.choice([True, False]):
                stat_change_choice_A_num = -stat_change_choice_A_num
            else:
                stat_change_choice_B_num = -stat_change_choice_B_num

            self.first_user_message = prompt_for_scenario.format(
                                        room_type = self.current_room,
                                        stat_change_choice_A = stat_change_choice_A + ": " + str(stat_change_choice_A_num) + f" (out of {stat_change_choice_A_cap})", 
                                        stat_change_choice_B = stat_change_choice_B + ": " + str(stat_change_choice_B_num) + f" (out of {stat_change_choice_B_cap})")
            self.stat_change_dict = {
                "Choice A": {"type": stat_change_choice_A, "value": stat_change_choice_A_num, "max": stat_change_choice_A_cap}, 
                "Choice B": {"type": stat_change_choice_B, "value": stat_change_choice_B_num, "max": stat_change_choice_B_cap}
                }
        else:
            self.stat_change_dict = stat_change_dict
    
    def get_stat_change(self) -> str:   
        stat_dict = {
            "hull": random.randint(5, 20),
            "oxygen": random.randint(5, 20),
            "coolant": random.randint(5, 20),
            "lives": 1,
            "chips": random.randint(10, 100)
        }

        stat_cap_dict = {
            "hull": "100 as one of the spaceship status",
            "oxygen": "100 as one of the spaceship status",
            "coolant": "100 as one of the spaceship status",
            "lives": "100 as one of the player health status",
            "chips": "500 initial amount for the player"
        }
        
        stat_to_change = random.choice(list(stat_dict.keys()))
        change_amount = stat_dict[stat_to_change]

        stat_cap = stat_cap_dict[stat_to_change]

        return stat_to_change, change_amount, stat_cap

    def parse_scenario_choices(self, text: str) -> dict:
        scenario_pattern = r"## Scenario\s*(.*?)\s*## Choice A"
        choice_a_pattern = r"## Choice A\s*(.*?)\s*## Choice B"
        choice_b_pattern = r"## Choice B\s*(.*)"

        scenario_match = re.search(scenario_pattern, text, re.DOTALL)
        choice_a_match = re.search(choice_a_pattern, text, re.DOTALL)
        choice_b_match = re.search(choice_b_pattern, text, re.DOTALL)

        # default templates
        default_scenario = "You encounter an unexpected challenge in the failing space station."
        default_choice_a = "Attempt a risky solution to fix the immediate problem."
        default_choice_b = "Look for an alternative path or workaround."

        # Store the extracted parts or fallback to defaults
        results = {
            "Scenario": scenario_match.group(1).strip() if scenario_match else default_scenario,
            "Choice A": choice_a_match.group(1).strip() if choice_a_match else default_choice_a,
            "Choice B": choice_b_match.group(1).strip() if choice_b_match else default_choice_b,
        }

        return results
    
    



        