from typing import Callable
from fschat.conversation_game import Conversation
import re


def question_header_in_output_stream(s):
    pattern = r'question \d+:'
    #if len(re.findall(pattern, s.lower())) !=0 and int(list(re.findall(number, s.lower()))[0]) == n:
    if len(re.findall(pattern, s.lower())) !=0:
        return True
    else:
        return False

def guess_in_output_stream(s):
    pattern = r"my guess of the word is:"
    if len(re.findall(pattern, s.lower())) != 0:
        return True
    else:
        return False
    
def generation_response(
    self,
    type: str,
    stream_iter_fn: Callable,
    conversation: Conversation,
    model_name: str,
    model_api_info: dict,
    temperature: float = 0.0,
    top_p: float = 1.0,
    max_new_tokens: int = 1024,
    state=None,
    use_recommended_config: bool = False,
) -> str:

    if use_recommended_config:
        recommended_config = model_api_info.get("recommended_config", None)
        if recommended_config is not None:
            temperature = recommended_config.get("temperature", 0.0)
            top_p = recommended_config.get("top_p", 1.0)
    # Generating new question
    print(model_name)
    prefix = None
    if type == 'question':
        prefix = f'Question {self.round + 1}:'
    elif type == 'answer':
        prefix = ' '
    elif type == 'taboo_guess':
        prefix = 'my guess of the word is:'
    else:
        raise NotImplementedError(f"response type: {type} is not implemented.")
    
    # API-dependent implementation, some APIs like mistral doens't accept a standalone per-turn prefix as input to the model
    # without prefix guiding, mistral doesn't do instruction-following...
    # TODO: add prefix to other API use as well, and keep displayed output consistent (no repetition of prefix been generated)
    if 'mistral' in model_name:
        conversation.append_message(
                conversation.roles[1], prefix
        )
    else:
        conversation.append_message(
                conversation.roles[1], None
        )
    
    stream_iter = stream_iter_fn(
            conversation,
            model_name,
            model_api_info,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
            state=state,
        )

    # some APIs' output streams won't include the given prefix, including 'claude', 'openai' and 'replicate'
    #if 'claude' in model_name or 'llama-3' in model_name or 'gpt' in model_name:
    #    if prefix != "":
    #        yield prefix + ' '
    
    # notice that openai API's output stream won't include the given prefix
    # we rely on the system prompt to have the model generate 

    prev_generation = None

    for i, data in enumerate(stream_iter):
        assert data["error_code"] == 0
        output_stream = data["text"].strip()
        
        if prev_generation is None:
            yield output_stream
            prev_generation = output_stream
        else:
            yield output_stream[len(prev_generation): ]
            prev_generation = output_stream
    
    output = data["text"].strip()

    # some APIs' output streams won't include the given prefix, including 'claude', 'openai' and 'replicate'
    # need to manually add the prefix to conversational history

    # 'gemini' doesn't repeat prefix
    # 'claude' doesn't repeat prefix
    # 'llama-3' with replicate API doesn't repeat prefix
    # 'gpt' doesn't repeat prefix
    # 'mistral' doesn't permits prefix, it generates the question number along the way
    if type == 'question':
        if question_header_in_output_stream(output):
            conversation.update_last_message(output)
        else:
            conversation.update_last_message(prefix + ' ' + output)
    elif type == 'taboo_guess':
        if guess_in_output_stream(output):
            conversation.update_last_message(output)
        else:
            conversation.update_last_message(prefix + ' ' + output)
    else:
        conversation.update_last_message(output)
    
    #if not self.is_llm_giving_answer(conversation):
    self.round += 1