from typing import Literal

from pydantic import BaseModel, SecretStr


class Config(BaseModel):
    timezone: int = 8  # UTC+8
    chat_api_key: SecretStr
    chat_base_url: str
    chat_model: str
    image_api_key: str


class SConfig(BaseModel):
    chat_response_level: Literal["disabled", "at", "all"] = "at"
    chat_min_corresponding_length: int = 5
    chat_prompt: str = ""
