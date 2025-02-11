# src/npc/base_npc.py

import random
from typing import Callable, Optional, Any, Tuple
import re
import os
import hashlib

from src.fschat.conversation_game import Conversation
from src.fschat.model_adapter import get_conversation_template
from utils import get_model_list

class BaseNPC:
    def __init__(
        self,
        model_name: Optional[str] = None,
        model_api_info: Optional[dict] = None,
        conversation: Optional[Conversation] = None,
        system_prompt: Optional[str] = None
    ) -> None:

        if model_name is None:
            models, _, api_endpoint_info = get_model_list(
                'src/config/api_endpoint.json', multimodal=False
            )
            # Use a specific model or a random one
            self.model_name = "gemini-1.5-pro"
            self.model_api_info = api_endpoint_info[self.model_name]
        else:
            self.model_name = model_name
            if model_api_info is None:
                models, _, api_endpoint_info = get_model_list(
                    'src/config/api_endpoint.json', multimodal=False
                )
                self.model_api_info = api_endpoint_info.get(self.model_name)
            else:
                self.model_api_info = model_api_info

        if conversation is None:
            self.conversation = get_conversation_template(self.model_name)
        else:
            self.conversation = conversation

        if system_prompt is not None:
            self.system_prompt = system_prompt
            self.conversation.set_system_message(self.system_prompt)
        else:
            self.system_prompt = None

    def parse_animations(self, text: str) -> Tuple[str, list]:
        """
        Parses the text to extract animations in the form <Animation>.
        Returns the cleaned text and a list of animations.
        """
        animation_pattern = r"<(.*?)>"
        animations = re.findall(animation_pattern, text)
        # Remove animations from text
        # cleaned_text = re.sub(animation_pattern, '', text).strip()
        
        #see <animations> here
        cleaned_text = text

        return cleaned_text, animations

    def generation_response(
        self,
        stream_iter_fn: Callable,
        conversation: Conversation,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_new_tokens: int = 150,
        state=None,
        use_recommended_config: bool = False,
    ) -> Tuple[str, list]:
        if use_recommended_config:
            recommended_config = self.model_api_info.get("recommended_config", None)
            if recommended_config is not None:
                temperature = recommended_config.get("temperature", 0.7)
                top_p = recommended_config.get("top_p", 0.9)
        # Generating NPC response
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
            output = data["text"].strip()
        # Parse animations
        cleaned_output, animations = self.parse_animations(output)
        # Update conversation with NPC response (use the cleaned output)
        conversation.update_last_message(cleaned_output)
        return cleaned_output, animations

    def update_user_conversation(
        self, conversation: Conversation, user_input: str
    ) -> None:
        conversation.append_message(conversation.roles[0], user_input)