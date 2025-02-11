import random
from abc import ABC, abstractmethod
from typing import Callable, Optional, Any, Dict
import re
import os
import hashlib

from src.fschat.conversation_game import Conversation
from src.fschat.model_adapter import get_conversation_template
from utils import get_model_list

def generate_hash(text: str) -> str:
    """Generate a 4-character hash from a given string."""
    return hashlib.md5(text.encode()).hexdigest()[:4]

def question_header_in_output_stream(s):
    pattern = r'^question \d+:'
    if len(re.findall(pattern, s.lower())) != 0:
        return True
    else:
        return False

def extract_text_after_question(s):
    """
    Checks if the input string starts with a question header of the form 'Question \d+:' 
    and extracts the content after the header.
    """
    pattern = r'^question \d+:'
    match = re.match(pattern, s.lower())
    
    if match:
        start_index = match.end()
        after_question = s[start_index:].strip()
        return True, after_question
    else:
        return False, ""

def guess_in_output_stream(s):
    pattern = r"my guess of the word is:"
    if len(re.findall(pattern, s.lower())) != 0:
        return True
    else:
        return False

class BaseGame(ABC):
    def __init__(
        self,
        difficulty: str,
        max_rounds: int,
        round: int = 0,
        user_id: Optional[int] = 0,
        username: Optional[str] = "anonymous",
        model_name: Optional[str] = None,  # Added 'model_name' parameter
        model_api_info: Optional[dict] = None,  # Added 'model_api_info' parameter
        conversation: Optional[Conversation] = None,  # Added 'conversation' parameter
        system_prompt: Optional[str] = None,  # Added 'system_prompt' parameter
        assistant_model_name: Optional[str] = "gpt-4o-2024-11-20",
        stat_change_dict: Optional[Dict[str, str]] = None,
    ) -> None:

        self.max_rounds = max_rounds
        # self.save_path = save_path  # Commented out; not used

        print(f"roblox game chosen difficulty: {difficulty}")

        if model_name is None:
            if difficulty == "Very_Hard":
                print("=========== initializing models in HARD mode ===========")
                models, _, api_endpoint_info = get_model_list(
                    'src/config/api_endpoint_hard.json', multimodal=False
                )
            else:
                print("=========== initializing models in REGULAR mode ===========")
                models, _, api_endpoint_info = get_model_list(
                    'src/config/api_endpoint.json', multimodal=False
                )
            if model_name is None:
                self.model_name = random.choice(models)
            else:
                self.model_name = model_name  # Use provided model_name
            
            self.model_api_info = api_endpoint_info.get(self.model_name)
        else:
            self.model_name = model_name
            if model_api_info:
                self.model_api_info = model_api_info
            else:
                models, _, api_endpoint_info = get_model_list(
                        'src/config/api_endpoint_backup.json', multimodal=False
                    )
                self.model_api_info = api_endpoint_info[model_name]  # Use provided model_api_info
        
        print(f"model api info: {self.model_api_info}")

        if conversation is None:
            self.conversation = get_conversation_template(self.model_name)
        else:
            self.conversation = conversation  # Use provided conversation

        if system_prompt is not None:
            self.system_prompt = system_prompt  # Use provided system_prompt
        else:
            self.system_prompt = None  # To be set by subclasses
        
        if stat_change_dict is not None:
            self.stat_change_dict = stat_change_dict
        else:
            self.stat_change_dict = None
        
        self.hint_prompt = None

        print("INIT ROUND: " + str(round))
        self.round = round
        self.game_over = False
        self.game_status = None
        self.user_id = user_id
        self.username = username

        # self.game_name = ""
        # self.game_rule = ""
        # self.game_start = False
        # self.generate_next_llm_query = False
        # self.next_llm_query_type = None

        self.available_levels = []
        self.game_level = None
        self.assistant_model_name = assistant_model_name
        
        models, _, api_endpoint_info = get_model_list(
            'src/config/api_endpoint.json', multimodal=False)
        self.assistant_model_api_info = api_endpoint_info[self.assistant_model_name]

        self.first_user_message = None  # The user's initial statement
        self.secret_system_message = None # FIXME (lanxiang): currently only used for Taboo. make configurable and elegant later

    def initialize_game(self, conversation: Conversation) -> None:
        if "o1" not in self.model_name:
            conversation.append_message(conversation.roles[0], self.first_user_message)
        else:
            conversation.append_message(conversation.roles[0], self.system_prompt + "\n\n" + self.first_user_message)

    def generation_response(
        self,
        type: str,
        stream_iter_fn: Callable,
        conversation: Conversation,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_new_tokens: int = 1024,
        state=None,
        use_recommended_config: bool = True,
    ) -> str:
        print("starting response generation...")
        if use_recommended_config:
            print("extracting recommended config...")
            recommended_config = self.model_api_info.get("recommended_config", None)
        
            # HACK (lanxiang): temporary forced overwrite
            temperature = recommended_config.get("temperature", 0.7)
            top_p = recommended_config.get("top_p", 1.0)
        # Generating new question
        print(self.model_name)
        prefix = None
        if type == 'question':
            prefix = f'Question {self.round + 1}:'
        elif type == 'answer':
            prefix = ' '
        elif type == 'taboo_guess':
            prefix = 'my guess of the word is:'
        else:
            raise NotImplementedError(f"response type: {type} is not implemented.")
        
        # HACK (lanxiang): temporary hack to deal with mistral instruction-following issues; set placeholders for AI responses
        # if 'mistral' in self.model_name:
        #     conversation.append_message(
        #         conversation.roles[1], prefix
        #     )
        # else:
        #     conversation.append_message(
        #         conversation.roles[1], None
        #     )

        stream_iter = stream_iter_fn(
            conversation,
            self.model_name,
            self.model_api_info,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
            state=state,
        )
        output = ""
        for data in stream_iter:
            assert data["error_code"] == 0
            # Update the output with the latest text from the API
            output = data["text"].strip()

        # checking akinator guess
        pattern = r"this is a guess"
        guess_flag = len(re.findall(pattern, output.lower())) != 0
    
        # Post-process the output based on the type
        if type == 'question' and self.round + 1 < self.max_rounds and not guess_flag:
            if question_header_in_output_stream(output):
                #conversation.update_last_message(output)
                _, output = extract_text_after_question(output)

            output = prefix + ' ' + output
        elif type == 'taboo_guess':
            if not guess_in_output_stream(output):
                output = prefix + ' ' + output
        
        conversation.update_last_message(output)
        
        self.round += 1
        return output
    
    def generation_assistant_response(
        self,
        type: str,
        stream_iter_fn: Callable,
        conversation: Conversation,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_new_tokens: int = 1024,
        state=None,
        use_recommended_config: bool = True,
        model_name: str = "gpt-4o-2024-11-20",
        # model_api_info: dict,
    ) -> str:
        if use_recommended_config:
                print("extracting recommended assistant model config...")
                recommended_config = self.assistant_model_api_info.get("recommended_config", None)
            
                # HACK (lanxiang): temporary forced overwrite
                temperature = recommended_config.get("temperature", 0.7)
                top_p = recommended_config.get("top_p", 1.0)
        
        # Generating new question
        model_name = model_name
        _, _, api_endpoint_info = get_model_list(
                'src/config/api_endpoint.json', multimodal=False
            )
        if type == "assistant" or "hint":
            print(self.assistant_model_name)
            model_name = self.assistant_model_name
            model_api_endpoint_info = api_endpoint_info[model_name]
        else:
            raise NotImplementedError(f"type: {type} not implemented.")

        stream_iter = stream_iter_fn(
            conversation,
            model_name,
            model_api_endpoint_info,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
            state=state,
        )
        output = ""
        # print(stream_iter)
        for data in stream_iter:
            assert data["error_code"] == 0
            # Update the output with the latest text from the API
            output = data["text"].strip()

        print("assistant responses:")
        print(output)

        conversation.update_last_message(output)
        
        return output

    def prepare_hint_prompt(self, game_history):
        print("starting preparing hint prompt...")
        parsed_history = []

        for _, conv in enumerate(game_history):
            role, message = conv
            parsed_history.append(f"[{role}]: {message}")
        
        print(f"parsed history: {parsed_history}")
        print(f"hint prompt: {self.hint_prompt}")

        # Join all entries into a single string
        return self.hint_prompt + "\n\nGame History:\n\n" + " ".join(parsed_history)

     # def update_conversation_with_user_choice(
    def update_user_conversation(
        self, conversation: Conversation, user_choice: str
    ) -> None:
        # conversation.roles[0] == "USER"
        # conversation.roles[1] == "ASSISTANT"
        conversation.append_message(conversation.roles[0], user_choice)

    def update_AI_conversation(
        self, conversation: Conversation, user_choice: str
    ) -> None:
        # conversation.roles[0] == "USER"
        # conversation.roles[1] == "ASSISTANT"
        conversation.append_message(conversation.roles[1], user_choice)

    def reach_max_round(self) -> bool:

        print("game round:")
        print(self.round)
        print("max round:")
        print(self.max_rounds)
        
        if self.round >= self.max_rounds:
            return True
        return False

    def set_game_status(self, status):
        self.game_over = True
        self.game_status = status
    
    # @abstractmethod
    # def is_llm_giving_answer(self, conversation: Conversation) -> bool:
    #     pass
    
    # def is_llm_triggering_termination(self, conversation: Conversation) -> bool:
    #     pass
    
    # def is_llm_illegal_input(self, input_text: str) -> bool:
    #     pass