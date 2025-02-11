import base64
import json

import requests
from fastchat.model.model_registry import model_info


def set_global_vars(controller_url_, enable_moderation_):
    global controller_url, enable_moderation
    controller_url = controller_url_
    enable_moderation = enable_moderation_


def get_model_list(register_api_endpoint_file, multimodal):
    # global api_endpoint_info

    models = []

    # Add models from the API providers
    if register_api_endpoint_file:
        api_endpoint_info = json.load(open(register_api_endpoint_file))
        for mdl, mdl_dict in api_endpoint_info.items():
            mdl_multimodal = mdl_dict.get("multimodal", False)
            if multimodal and mdl_multimodal:
                models += [mdl]
            elif not multimodal and not mdl_multimodal:
                models += [mdl]
    else:
        raise ValueError("register_api_endpoint_file is required")

    # Remove anonymous models
    models = list(set(models))
    visible_models = models.copy()
    for mdl in visible_models:
        if mdl not in api_endpoint_info:
            continue
        mdl_dict = api_endpoint_info[mdl]
        if mdl_dict["anony_only"]:
            visible_models.remove(mdl)

    # Sort models and add descriptions
    priority = {k: f"___{i:03d}" for i, k in enumerate(model_info)}
    models.sort(key=lambda x: priority.get(x, x))
    visible_models.sort(key=lambda x: priority.get(x, x))
    print(f"All models: {models}")
    print(f"Visible models: {visible_models}")
    return visible_models, models, api_endpoint_info


# Read the CSS file
def load_css(file_name):
    with open(file_name) as f:
        return f.read()


# Add background
def get_base64_of_bin_file(bin_file):
    with open(bin_file, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()


def add_bg_from_local(image_file):
    bin_str = get_base64_of_bin_file(image_file)
    return f"""
<style>
.stApp {{
    background-image: url("data:image/jpg;base64,{bin_str}");
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
}}
</style>
"""